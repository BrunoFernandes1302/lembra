"""Modo agente: o LLM recebe FERRAMENTAS e decide sozinho quais usar, em que ordem.

Fluxo fixo (RAG normal):   pergunta -> busca -> resposta
Agente:                    pergunta -> LLM pensa -> chama ferramenta -> vê o resultado
                           -> pensa de novo -> ... -> responde   (no máximo MAX_PASSOS)

O ciclo é escrito à mão (sem o "modo automático" da biblioteca) para ficar visível:
  1. mandamos a conversa + a lista de ferramentas ao LLM;
  2. se ele pedir ferramentas, NOSSO código as executa e devolve os resultados;
  3. repete até ele responder em texto ou o limite de passos acabar.
O LLM nunca executa nada sozinho: ele só PEDE; quem executa (e controla) é o código.
"""

from __future__ import annotations

import ast
import calendar
import logging
import operator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

from .config import Settings
from .supabase import Trecho

logger = logging.getLogger(__name__)

MAX_PASSOS = 5
# Hora de Brasília como deslocamento FIXO (-03:00): o Brasil não tem horário de verão desde 2019. Não usa
# zoneinfo de propósito: ele depende do banco de fusos do SISTEMA, que pode não existir no servidor
# (aí toda pergunta quebraria com ZoneInfoNotFoundError).
BRASILIA = timezone(timedelta(hours=-3))


def agora_sp() -> datetime:
    return datetime.now(BRASILIA)


DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira", "sexta-feira", "sábado", "domingo"]

PROMPT_AGENTE = """Você é o Lembra, um assistente de organização pessoal que conhece a vida do usuário \
pelas memórias que ele mesmo registrou. Você tem ferramentas para consultar essas memórias.

Regras:
- Use as ferramentas para encontrar a informação antes de responder. Você pode buscar mais de uma
  vez, com termos diferentes, se a primeira busca não trouxer o que precisa.
- Responda usando APENAS o que as ferramentas retornaram. Não invente fatos.
- Para QUALQUER conta (somas, diferenças, médias), use a ferramenta calcular — não faça de cabeça.
- Para datas: use data_de_hoje; para "quantos dias faltam/passaram", use dias_ate (nunca conte
  dias de cabeça nem somando meses).
- Para eventos RECORRENTES ("toda última quinta do mês", "todo dia 5", "toda terça", "a cada 15
  dias"), use proxima_ocorrencia e responda com a data concreta, não só com a regra. Ela já usa a
  data de hoje e já devolve quantos dias faltam: não chame data_de_hoje nem dias_ate junto.
- Cite os trechos usados pelo número que a ferramenta informou, um por colchete: [1] [2].
  Resultados de calcular, data_de_hoje, dias_ate e proxima_ocorrencia não são trechos: não os cite.
- Interprete a pergunta pelo sentido, não ao pé da letra.
- Se, depois de buscar, não encontrar a resposta, diga claramente que não encontrou nas memórias.
- Fale com o usuário na segunda pessoa ("você"), em português do Brasil, de forma natural."""

# Descrição das ferramentas para o LLM (JSON Schema). A descrição é o que o LLM lê para decidir.
DECLARACOES = [
    {"name": "buscar_memorias",
     "description": "Busca por SIGNIFICADO nas memórias do usuário (encontra 'pet' quando a memória diz "
                    "'cachorra'). Retorna trechos numerados para citar.",
     "parameters": {"type": "object", "properties": {
         "consulta": {"type": "string", "description": "o que procurar, em linguagem natural"},
         "categoria": {"type": "string", "description": "opcional: restringe a uma categoria"}},
         "required": ["consulta"]}},
    {"name": "listar_memorias",
     "description": "Lista memórias por filtro EXATO: de uma categoria e/ou que contenham um texto. "
                    "Use para 'o que eu registrei em X' ou para conferir todas as de um assunto.",
     "parameters": {"type": "object", "properties": {
         "categoria": {"type": "string"},
         "texto_contem": {"type": "string", "description": "palavra que deve aparecer no texto"}}}},
    {"name": "listar_categorias",
     "description": "Lista as categorias que o usuário criou e quantas memórias há em cada uma.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "calcular",
     "description": "Faz contas com precisão. Aceita números, + - * / ( ) e ponto decimal. "
                    "Ex.: '1800 + 450 + 120'.",
     "parameters": {"type": "object", "properties": {"expressao": {"type": "string"}},
                    "required": ["expressao"]}},
    {"name": "dias_ate",
     "description": "Conta quantos dias faltam de HOJE até uma data (ou quantos passaram, se for no "
                    "passado). Se o ano não for informado, usa a próxima ocorrência (bom para aniversários).",
     "parameters": {"type": "object", "properties": {
         "dia": {"type": "integer"}, "mes": {"type": "integer"},
         "ano": {"type": "integer", "description": "opcional"}},
         "required": ["dia", "mes"]}},
    {"name": "proxima_ocorrencia",
     "description": "Calcula as próximas datas de um evento RECORRENTE a partir de hoje (já sabe a data de "
                    "hoje e devolve quantos dias faltam). Descreva a regra: "
                    "tipo 'dia_do_mes' (todo dia 5 → dia=5); 'dia_da_semana' (toda terça → dia_semana); "
                    "'ordem_no_mes' (2ª segunda do mês → ordem=2; ÚLTIMA quinta → ordem=-1; com dia_semana); "
                    "'a_cada_n_dias' (a cada 15 dias desde 01/10/2026 → n=15, a_partir_de).",
     "parameters": {"type": "object", "properties": {
         "tipo": {"type": "string", "enum": ["dia_do_mes", "dia_da_semana", "ordem_no_mes", "a_cada_n_dias"]},
         "dia": {"type": "integer", "description": "1 a 31 (dia_do_mes)"},
         "dia_semana": {"type": "string", "enum": DIAS},
         "ordem": {"type": "integer", "description": "1 a 5, ou -1 para a última (ordem_no_mes)"},
         "n": {"type": "integer", "description": "intervalo em dias (a_cada_n_dias)"},
         "a_partir_de": {"type": "string", "description": "dd/mm/aaaa de uma ocorrência conhecida (a_cada_n_dias)"},
         "quantidade": {"type": "integer", "description": "quantas próximas datas (padrão 1, máx. 6)"}},
         "required": ["tipo"]}},
    {"name": "data_de_hoje",
     "description": "Retorna a data e o dia da semana de hoje (fuso de Brasília).",
     "parameters": {"type": "object", "properties": {}}},
]


# ---------------------------------------------------------------- recorrências (calculadas, não chutadas)
def _no_mes(ano: int, mes: int, tipo: str, dia=None, dia_semana=None, ordem=None) -> tuple[date | None, bool]:
    """A ocorrência DENTRO de um mês (ou None se não existir, ex.: 5ª segunda). Devolve (data, ajustada)."""
    ultimo = calendar.monthrange(ano, mes)[1]
    if tipo == "dia_do_mes":  # dia já validado (1-31); 29-31 em mês curto vira o último dia
        return date(ano, mes, min(int(dia), ultimo)), int(dia) > ultimo  # dia 31 em fev → último dia
    alvo = DIAS.index(dia_semana)
    dias = [d for d in range(1, ultimo + 1) if date(ano, mes, d).weekday() == alvo]
    ordem = int(ordem)
    if ordem == -1:
        return date(ano, mes, dias[-1]), False
    return (date(ano, mes, dias[ordem - 1]), False) if 1 <= ordem <= len(dias) else (None, False)


def _ler_data(texto: str) -> date:
    """Aceita dd/mm/aaaa e aaaa-mm-dd (formato comum dos LLMs); outro formato vira erro claro."""
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(texto).strip(), formato).date()
        except ValueError:
            continue
    raise ValueError(f"data inválida: {texto!r} (use dd/mm/aaaa)")


def proximas_ocorrencias(tipo: str, hoje: date, quantidade: int = 1, dia=None, dia_semana=None, ordem=None,
                         n=None, a_partir_de=None) -> list[tuple[date, bool]]:
    """Próximas datas (a partir de hoje, inclusive) de uma regra recorrente."""
    quantidade = max(1, min(int(quantidade or 1), 6))
    if tipo == "dia_do_mes" and not 1 <= int(dia) <= 31:
        raise ValueError(f"dia precisa estar entre 1 e 31 (recebi {dia})")
    if tipo == "ordem_no_mes" and int(ordem) not in (-1, 1, 2, 3, 4, 5):
        raise ValueError(f"ordem precisa ser 1 a 5, ou -1 para a última (recebi {ordem})")
    if tipo == "dia_da_semana":
        primeira = hoje + timedelta(days=(DIAS.index(dia_semana) - hoje.weekday()) % 7)
        return [(primeira + timedelta(weeks=k), False) for k in range(quantidade)]
    if tipo == "a_cada_n_dias":
        n = int(n)
        if n < 1:
            raise ValueError("n precisa ser pelo menos 1")
        base = _ler_data(a_partir_de)
        saltos = max(0, -(-(hoje - base).days // n))  # arredonda para cima: primeira ocorrência >= hoje
        return [(base + timedelta(days=n * (saltos + k)), False) for k in range(quantidade)]
    if tipo not in ("dia_do_mes", "ordem_no_mes"):
        raise ValueError(f"tipo desconhecido: {tipo}")
    datas, ano, mes = [], hoje.year, hoje.month
    for _ in range(24):  # olha até 2 anos à frente (ex.: 5ª segunda é rara)
        d, ajustada = _no_mes(ano, mes, tipo, dia, dia_semana, ordem)
        if d and d >= hoje:
            datas.append((d, ajustada))
            if len(datas) == quantidade:
                break
        ano, mes = (ano + 1, 1) if mes == 12 else (ano, mes + 1)
    return datas


# ---------------------------------------------------------------- calculadora segura
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg, ast.UAdd: operator.pos}


def calcular_seguro(expressao: str) -> float:
    """Avalia só números e + - * / ( ). NUNCA usa eval(): eval executaria qualquer código
    que o LLM (ou alguém manipulando o LLM) escrevesse."""
    expressao = expressao.replace(",", ".").replace("x", "*").replace("×", "*")
    if len(expressao) > 200:
        raise ValueError("expressão longa demais")

    def avaliar(no):
        if isinstance(no, ast.Expression):
            return avaliar(no.body)
        if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)):
            return no.value
        if isinstance(no, ast.BinOp) and type(no.op) in _OPS:
            return _OPS[type(no.op)](avaliar(no.left), avaliar(no.right))
        if isinstance(no, ast.UnaryOp) and type(no.op) in _OPS:
            return _OPS[type(no.op)](avaliar(no.operand))
        raise ValueError("só números e + - * / ( ) são permitidos")

    return avaliar(ast.parse(expressao, mode="eval"))


# ---------------------------------------------------------------- ferramentas
@dataclass
class Ferramentas:
    """As ações que o agente pode pedir. Todas usam o repositório DO USUÁRIO (com o crachá
    dele), então o agente também só enxerga as memórias de quem perguntou (RLS)."""

    repo: object
    settings: Settings
    categoria_padrao: str | None = None
    fontes: list[Trecho] = field(default_factory=list)

    def _numerar(self, t: Trecho) -> int:
        for i, f in enumerate(self.fontes, 1):
            if f.texto == t.texto:
                return i
        self.fontes.append(t)
        return len(self.fontes)

    def buscar_memorias(self, consulta: str, categoria: str | None = None) -> dict:
        from . import rag

        trechos = rag.buscar(self.repo, consulta, categoria or self.categoria_padrao, self.settings)
        return {"trechos": [{"n": self._numerar(t), "texto": t.texto, "categoria": t.metadados.get("categoria"),
                             "data": t.metadados.get("data"), "similaridade": round(t.similaridade, 2)}
                            for t in trechos]}

    def listar_memorias(self, categoria: str | None = None, texto_contem: str | None = None) -> dict:
        cat = categoria or self.categoria_padrao
        mems = self.repo.listar_memorias(cat.strip().lower() if cat else None)
        if texto_contem:
            mems = [m for m in mems if texto_contem.lower() in m["texto"].lower()]
        saida = []
        for m in mems[:30]:
            t = Trecho(m["texto"], {"memoria_id": m["id"], "categoria": m["categoria"], "data": m.get("data_evento")}, 1.0)
            saida.append({"n": self._numerar(t), "texto": m["texto"][:600], "categoria": m["categoria"],
                          "data": m.get("data_evento")})
        return {"total": len(mems), "memorias": saida}

    def listar_categorias(self) -> dict:
        return {"categorias": self.repo.listar_categorias()}

    def calcular(self, expressao: str) -> dict:
        return {"expressao": expressao, "resultado": round(calcular_seguro(expressao), 6)}

    def data_de_hoje(self) -> dict:
        agora = agora_sp()
        return {"data": agora.strftime("%d/%m/%Y"), "dia_da_semana": DIAS[agora.weekday()]}

    def dias_ate(self, dia: int, mes: int, ano: int | None = None, hoje: date | None = None) -> dict:
        hoje = hoje or agora_sp().date()
        alvo = date(int(ano) if ano else hoje.year, int(mes), int(dia))
        if ano is None and alvo < hoje:  # sem ano: próxima ocorrência (ex.: aniversário)
            alvo = date(hoje.year + 1, int(mes), int(dia))
        dias = (alvo - hoje).days
        return {"data": alvo.strftime("%d/%m/%Y"), "dia_da_semana": DIAS[alvo.weekday()],
                "dias": dias, "sentido": "faltam" if dias >= 0 else "passaram"}

    def proxima_ocorrencia(self, tipo: str, hoje: date | None = None, **regra) -> dict:
        hoje = hoje or agora_sp().date()
        datas = proximas_ocorrencias(tipo, hoje, **regra)
        if not datas:
            return {"erro": "essa regra não tem ocorrência nos próximos 2 anos"}
        return {"hoje": hoje.strftime("%d/%m/%Y"), "ocorrencias": [
            {"data": d.strftime("%d/%m/%Y"), "dia_da_semana": DIAS[d.weekday()], "dias": (d - hoje).days,
             **({"ajustada_para_o_ultimo_dia_do_mes": True} if aj else {})} for d, aj in datas]}

    def executar(self, nome: str, args: dict) -> dict:
        if nome not in {d["name"] for d in DECLARACOES}:
            return {"erro": f"ferramenta desconhecida: {nome}"}
        try:
            return getattr(self, nome)(**(args or {}))
        except Exception as e:  # noqa: BLE001 — erro de ferramenta vira informação para o LLM
            return {"erro": str(e)}


# ---------------------------------------------------------------- motor (LLM com ferramentas)
@dataclass
class Chamada:
    nome: str
    args: dict


class Motor(Protocol):
    def proximo(self) -> tuple[str | None, list[Chamada]]: ...
    def devolver(self, resultados: list[tuple[str, dict]]) -> None: ...
    def finalizar(self) -> str: ...


class MotorGemini:
    """Conversa com o Gemini guardando o histórico: pergunta, pedidos de ferramenta e resultados."""

    def __init__(self, s: Settings, sistema: str, pergunta: str):
        from google import genai
        from google.genai import types

        self.types = types
        self.client = genai.Client(api_key=s.gemini_api_key)
        self.modelo = s.gemini_model
        self.sistema = sistema
        self.historico = [types.Content(role="user", parts=[types.Part.from_text(text=pergunta)])]
        self.ferramentas = [types.Tool(function_declarations=[
            types.FunctionDeclaration(name=d["name"], description=d["description"],
                                      parameters_json_schema=d["parameters"]) for d in DECLARACOES])]

    def _gerar(self, com_ferramentas: bool):
        t = self.types
        cfg = t.GenerateContentConfig(
            system_instruction=self.sistema,
            tools=self.ferramentas if com_ferramentas else None,
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True))
        return self.client.models.generate_content(model=self.modelo, contents=self.historico, config=cfg)

    def proximo(self):
        r = self._gerar(True)
        chamadas = [Chamada(fc.name, dict(fc.args or {})) for fc in (r.function_calls or [])]
        if chamadas:
            self.historico.append(r.candidates[0].content)  # o pedido do modelo entra no histórico
            return None, chamadas
        return (r.text or "").strip(), []

    def devolver(self, resultados):
        t = self.types
        self.historico.append(t.Content(role="user", parts=[
            t.Part.from_function_response(name=nome, response=res) for nome, res in resultados]))

    def finalizar(self):
        # limite de passos atingido: pede a resposta final SEM ferramentas
        self.historico.append(self.types.Content(role="user", parts=[self.types.Part.from_text(
            text="Responda agora com o que já encontrou, sem usar mais ferramentas.")]))
        return (self._gerar(False).text or "").strip()


# ---------------------------------------------------------------- o ciclo do agente
def _resumo(nome: str, args: dict, res: dict) -> str:
    if "erro" in res:
        return f"erro: {res['erro']}"
    if nome == "buscar_memorias":
        return f"{len(res['trechos'])} trecho(s) encontrado(s)"
    if nome == "listar_memorias":
        return f"{res['total']} memória(s)"
    if nome == "listar_categorias":
        return f"{len(res['categorias'])} categoria(s)"
    if nome == "calcular":
        return f"= {res['resultado']:g}"
    if nome == "data_de_hoje":
        return f"{res['data']} ({res['dia_da_semana']})"
    if nome == "dias_ate":
        return f"{abs(res['dias'])} dias até {res['data']}"
    if nome == "proxima_ocorrencia":
        prox = res["ocorrencias"][0]
        return f"próxima: {prox['data']} ({prox['dia_da_semana']})"
    return "ok"


def executar_agente(repo, pergunta: str, categoria: str | None, s: Settings, motor: Motor | None = None):
    """Roda o agente e devolve (texto, fontes, passos)."""
    ferramentas = Ferramentas(repo, s, categoria_padrao=categoria)
    from .rag import extras_do_usuario

    sistema = PROMPT_AGENTE + extras_do_usuario(s)
    if categoria:
        sistema += f'\n\nO usuário restringiu a pergunta à categoria "{categoria}".'
    motor = motor or MotorGemini(s, sistema, pergunta)
    passos: list[dict] = []

    for _ in range(MAX_PASSOS):
        texto, chamadas = motor.proximo()
        if not chamadas:
            return texto, ferramentas.fontes, passos
        resultados = []
        for c in chamadas:
            res = ferramentas.executar(c.nome, c.args)
            passos.append({"ferramenta": c.nome, "argumentos": c.args, "resumo": _resumo(c.nome, c.args, res)})
            resultados.append((c.nome, res))
        motor.devolver(resultados)

    logger.info("agente atingiu o limite de %s passos", MAX_PASSOS)
    return motor.finalizar(), ferramentas.fontes, passos

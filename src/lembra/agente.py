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
import logging
import operator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from .config import Settings
from .supabase import Trecho

logger = logging.getLogger(__name__)

MAX_PASSOS = 5
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
- Cite os trechos usados pelo número que a ferramenta informou, um por colchete: [1] [2].
  Resultados de calcular, data_de_hoje e dias_ate não são trechos: não os cite.
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
    {"name": "data_de_hoje",
     "description": "Retorna a data e o dia da semana de hoje (fuso de Brasília).",
     "parameters": {"type": "object", "properties": {}}},
]


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
        agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
        return {"data": agora.strftime("%d/%m/%Y"), "dia_da_semana": DIAS[agora.weekday()]}

    def dias_ate(self, dia: int, mes: int, ano: int | None = None, hoje: date | None = None) -> dict:
        hoje = hoje or datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        alvo = date(int(ano) if ano else hoje.year, int(mes), int(dia))
        if ano is None and alvo < hoje:  # sem ano: próxima ocorrência (ex.: aniversário)
            alvo = date(hoje.year + 1, int(mes), int(dia))
        dias = (alvo - hoje).days
        return {"data": alvo.strftime("%d/%m/%Y"), "dia_da_semana": DIAS[alvo.weekday()],
                "dias": dias, "sentido": "faltam" if dias >= 0 else "passaram"}

    def executar(self, nome: str, args: dict) -> dict:
        if nome not in {d["name"] for d in DECLARACOES}:
            return {"erro": f"ferramenta desconhecida: {nome}"}
        try:
            return getattr(self, nome)(**(args or {}))
        except Exception as e:  # erro vira informação para o LLM, não derruba o app
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

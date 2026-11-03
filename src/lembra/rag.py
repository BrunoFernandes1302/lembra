"""RAG: os dois fluxos do Lembra.

ALIMENTAR:  texto -> chunks -> embeddings -> banco (numa transação)
PERGUNTAR:  pergunta -> embedding -> busca (com filtro de categoria opcional)
            -> prompt com os trechos -> LLM -> resposta com fontes

R = Retrieval   : achar os chunks mais parecidos com a pergunta.
A = Augmented   : colar esses chunks no prompt, como "material de consulta".
G = Generation  : o LLM responde usando SÓ esse material.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from pydantic import BaseModel
from typing import Protocol

from .chunking import chunk_text
from .config import Settings, com_config_do_usuario, embedder_de, get_settings
from .llm import get_llm
from .supabase import Trecho

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Você é o Lembra, um assistente de organização pessoal que conhece a vida do usuário \
pelas memórias que ele mesmo registrou.

Regras:
- Responda usando APENAS as memórias fornecidas entre <memorias>. Não invente fatos.
- Ignore memórias que não tenham relação com a pergunta.
- Interprete a pergunta pelo sentido, não ao pé da letra: palavras mais gerais incluem as mais específicas (por exemplo, uma consulta com a nutricionista responde a "tenho algum compromisso de saúde?"; um carro responde a "quais veículos eu tenho?"). Quando uma memória responder à pergunta dessa forma, vá direto à resposta, sem começar dizendo que não encontrou.
- Cite as memórias usadas no formato [1], [2]...
- Se as memórias não tiverem a resposta, diga claramente que não encontrou isso nas memórias.
- Fale com o usuário na segunda pessoa ("você"), em português do Brasil, de forma natural."""


def settings_do_usuario(repo, settings: Settings | None = None) -> Settings:
    """Padrões do servidor + a configuração que o usuário salvou no app."""
    s = settings or get_settings()
    obter = getattr(repo, "obter_config", None)
    return com_config_do_usuario(s, obter() if obter else None)


def prompt_do_sistema(s: Settings) -> str:
    if not s.instrucoes.strip():
        return SYSTEM_PROMPT
    # As preferências do usuário entram DEPOIS das regras e não podem anulá-las.
    return (SYSTEM_PROMPT + "\n\nPreferências do usuário sobre o formato da resposta (siga, desde que não "
            "contrariem as regras acima):\n" + s.instrucoes.strip())


class Repositorio(Protocol):
    def salvar_memoria(self, texto, categoria, data_evento, chunks, vetores, modelo) -> str: ...
    def buscar(self, vetor, k, categoria=None, modelo=None) -> list[Trecho]: ...


@dataclass
class Resposta:
    texto: str
    fontes: list[Trecho]
    gerada_por_ia: bool = False
    passos: list[dict] = field(default_factory=list)  # modo agente: ferramentas usadas


def alimentar(
    repo: Repositorio, texto: str, categoria: str = "geral", data_evento: str = "",
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Quebra, gera embeddings e salva. Retorna (id da memória, número de chunks)."""
    s = settings_do_usuario(repo, settings)
    chunks = chunk_text(texto, s.chunk_size, s.chunk_overlap)
    if not chunks:
        raise ValueError("A memória está vazia")
    vetores = embedder_de(s).embed_documents(chunks)
    return repo.salvar_memoria(texto, categoria, data_evento, chunks, vetores, s.embedding_model), len(chunks)


def editar(
    repo, memoria_id: str, texto: str, categoria: str, data_evento: str = "",
    settings: Settings | None = None,
) -> dict | None:
    """Edita uma memória. Só recalcula chunks e vetores se o TEXTO mudou (economiza tempo e cota);
    mudar só categoria ou data atualiza apenas os rótulos."""
    s = settings_do_usuario(repo, settings)
    atual = repo.obter_memoria(memoria_id)
    if atual is None:
        return None
    if texto == atual["texto"]:
        repo.atualizar_memoria(memoria_id, texto, categoria, data_evento)
        return {"id": memoria_id, "recalculou": False}
    chunks = chunk_text(texto, s.chunk_size, s.chunk_overlap)
    if not chunks:
        raise ValueError("A memória está vazia")
    vetores = embedder_de(s).embed_documents(chunks)
    repo.atualizar_memoria(memoria_id, texto, categoria, data_evento, chunks, vetores, s.embedding_model)
    return {"id": memoria_id, "recalculou": True, "chunks": len(chunks)}


def buscar(
    repo: Repositorio, pergunta: str, categoria: str | None = None, settings: Settings | None = None,
    vetor: list[float] | None = None,
) -> list[Trecho]:
    """Retrieval: embedding da pergunta -> vizinhos mais próximos no banco."""
    s = settings_do_usuario(repo, settings) if settings is None else settings
    if vetor is None:
        vetor = embedder_de(s).embed_query(pergunta)
    return repo.buscar(vetor, s.top_k, categoria, s.embedding_model)


def _config_e_vetor(repo, pergunta: str, settings: Settings | None) -> tuple[Settings, list[float] | None]:
    """Lê a config do usuário (banco) e gera o embedding da pergunta (Gemini) AO MESMO TEMPO:
    um não depende do outro (o modelo de embeddings é do servidor, não do usuário).
    Tempo total = o da mais lenta, e não a soma das duas."""
    base = settings or get_settings()
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_cfg = ex.submit(settings_do_usuario, repo, settings)
        f_vet = ex.submit(embedder_de(base).embed_query, pergunta)
        s = f_cfg.result()
        try:
            vetor = f_vet.result()
        except Exception:  # noqa: BLE001 — se falhar aqui, buscar() tenta de novo
            vetor = None
    return s, vetor


def montar_prompt(pergunta: str, trechos: list[Trecho]) -> str:
    """Augmentation: junta pergunta + trechos recuperados num único prompt."""
    blocos = []
    for i, t in enumerate(trechos, start=1):
        quando = f' data="{t.metadados["data"]}"' if t.metadados.get("data") else ""
        categoria = t.metadados.get("categoria", "geral")
        blocos.append(f'<memoria indice="{i}" categoria="{categoria}"{quando}>\n{t.texto}\n</memoria>')
    contexto = "\n".join(blocos) or "(nenhuma memória encontrada)"
    return f"<memorias>\n{contexto}\n</memorias>\n\nPergunta: {pergunta}"


# Heurística (regra prática, não garantia): as notas absolutas variam por modelo, então um corte
# fixo não funciona. Guardamos só os trechos a até MARGEM do melhor. Nos testes com o Gemini, o
# trecho certo ficou 0,07-0,15 acima do 2º colocado. Com IA, isso não é preciso: o LLM ignora o
# que não tem relação. Sem IA, o usuário veria ruído.
MARGEM_RELEVANCIA = 0.05


def filtrar_proximos_do_melhor(trechos: list[Trecho], margem: float = MARGEM_RELEVANCIA) -> list[Trecho]:
    """Guarda só os trechos com nota até `margem` abaixo da melhor."""
    if not trechos:
        return trechos
    melhor = max(t.similaridade for t in trechos)
    return [t for t in trechos if t.similaridade >= melhor - margem]


def perguntar(
    repo: Repositorio, pergunta: str, categoria: str | None = None, settings: Settings | None = None
) -> Resposta:
    s, vetor = _config_e_vetor(repo, pergunta, settings)
    if s.usar_ia and s.modo_agente and s.llm_provider == "gemini":
        resposta = _perguntar_com_agente(repo, pergunta, categoria, s)
        if resposta is not None:
            return resposta
    trechos = buscar(repo, pergunta, categoria, s, vetor)
    if not trechos:
        return Resposta("Ainda não encontrei memórias suas sobre isso. Registre algumas primeiro.", [])
    llm = get_llm(s) if s.usar_ia else None
    if llm is None:  # sem IA: só a busca, então o próprio usuário lê os trechos
        return Resposta("Encontrei estas memórias relacionadas:",
                        filtrar_proximos_do_melhor(trechos, s.margem_relevancia))
    try:
        texto = llm.gerar(prompt_do_sistema(s), montar_prompt(pergunta, trechos))
    except Exception as e:  # limite diário, rede, chave inválida...: não derruba o app
        logger.warning("LLM falhou (%s): %s", type(e).__name__, e)
        return Resposta(
            "Não consegui gerar uma resposta agora (o serviço de IA está indisponível ou atingiu o "
            "limite). Estas são as memórias que encontrei:",
            trechos,
        )
    return Resposta(texto, trechos, gerada_por_ia=True)


def _perguntar_com_agente(repo, pergunta: str, categoria: str | None, s: Settings) -> Resposta | None:
    """Modo agente. Se o serviço de IA falhar, devolve None e o fluxo normal assume."""
    from .agente import executar_agente

    try:
        texto, fontes, passos = executar_agente(repo, pergunta, categoria, s)
    except Exception as e:  # noqa: BLE001 — degradação graciosa: cai para o RAG normal
        logger.warning("agente falhou (%s): %s", type(e).__name__, e)
        return None
    return Resposta(texto or "Não consegui chegar a uma resposta.", fontes, gerada_por_ia=True, passos=passos)


def previa_chunking(texto: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Laboratório: mostra como um texto SERIA quebrado, sem salvar nada."""
    return chunk_text(texto, chunk_size, chunk_overlap)


def reprocessar(repo, settings: Settings | None = None) -> dict:
    """Refaz chunks e vetores de TODAS as memórias do usuário com a configuração atual.
    Necessário depois de mudar tamanho/sobreposição do chunk (o índice é descartável;
    a fonte da verdade, o texto original, não muda)."""
    s = settings_do_usuario(repo, settings)
    memorias = repo.listar_memorias(limite=1000)
    pedacos = {m["id"]: chunk_text(m["texto"], s.chunk_size, s.chunk_overlap) for m in memorias}
    todos = [c for cs in pedacos.values() for c in cs]
    if not todos:
        return {"memorias": 0, "chunks": 0}
    vetores = embedder_de(s).embed_documents(todos)  # um lote só: menos chamadas à API
    i = 0
    for m in memorias:
        n = len(pedacos[m["id"]])
        repo.atualizar_memoria(m["id"], m["texto"], m["categoria"], m.get("data_evento") or "",
                               pedacos[m["id"]], vetores[i : i + n], s.embedding_model)
        i += n
    return {"memorias": len(memorias), "chunks": len(todos)}


MAX_BLOCOS_IMPORTACAO = 200  # protege a cota do Gemini e o tempo máximo de uma requisição


def importar_conversa(
    repo, conteudo: str, nome_conversa: str, categoria: str = "conversas",
    pausa_horas: float = 6, confirmar: bool = False, settings: Settings | None = None,
) -> dict:
    """Importa uma conversa exportada do WhatsApp. Com confirmar=False só mostra a PRÉVIA
    (nada é salvo e nenhuma IA é chamada)."""
    from . import whatsapp

    msgs = whatsapp.ler_exportacao(conteudo)
    if not msgs:
        raise ValueError("Não reconheci mensagens nesse arquivo. Exporte pelo WhatsApp: "
                         "conversa → ⋮ → Mais → Exportar conversa → Sem mídia.")
    blocos = whatsapp.agrupar(msgs, pausa_horas=pausa_horas)
    resumo = {
        "mensagens": len(msgs), "blocos": len(blocos),
        "participantes": sorted({m.autor for m in msgs}),
        "de": msgs[0].quando.strftime("%d/%m/%Y"), "ate": msgs[-1].quando.strftime("%d/%m/%Y"),
        "exemplo": whatsapp.texto_da_memoria(blocos[0], nome_conversa)[:600],
    }
    if len(blocos) > MAX_BLOCOS_IMPORTACAO:
        raise ValueError(f"A conversa gerou {len(blocos)} blocos (máximo {MAX_BLOCOS_IMPORTACAO}). "
                         "Exporte um período menor ou divida o arquivo.")
    if not confirmar:
        return {**resumo, "salvo": False}

    s = settings_do_usuario(repo, settings)
    textos = [whatsapp.texto_da_memoria(b, nome_conversa) for b in blocos]
    pedacos = [chunk_text(t, s.chunk_size, s.chunk_overlap) for t in textos]
    vetores = embedder_de(s).embed_documents([c for cs in pedacos for c in cs])  # em lotes
    i = 0
    for b, t, cs in zip(blocos, textos, pedacos):
        repo.salvar_memoria(t, categoria, b.inicio.strftime("%d/%m/%Y"), cs, vetores[i : i + len(cs)],
                            s.embedding_model)
        i += len(cs)
    return {**resumo, "salvo": True, "memorias_criadas": len(blocos), "chunks": i}


class SugestaoCategoria(BaseModel):
    categoria: str
    e_nova: bool
    motivo: str


PROMPT_CATEGORIA = """Você organiza as memórias pessoais de um usuário em categorias.
Recebe as CATEGORIAS EXISTENTES dele e uma MEMÓRIA nova. Escolha a categoria mais adequada.
- Prefira SEMPRE uma categoria existente quando ela servir razoavelmente (e_nova = false).
- Só proponha uma nova se nenhuma existente servir (e_nova = true): nome curto (1 ou 2 palavras),
  em português, minúsculas, genérico o bastante para outras memórias parecidas (ex.: "saúde",
  "finanças", "viagens"; nunca algo específico como "consulta do dia 12").
- motivo: uma frase curta."""


def sugerir_categoria(repo, texto: str, settings: Settings | None = None) -> dict | None:
    """Classificação "zero-shot": o LLM escolhe entre as categorias QUE O USUÁRIO CRIOU
    (ou propõe uma nova). Devolve None se a IA estiver desligada ou indisponível."""
    s = settings_do_usuario(repo, settings)
    llm = get_llm(s) if s.usar_ia else None
    if llm is None or not hasattr(llm, "gerar_json") or len(texto.strip()) < 15:
        return None
    existentes = [c["nome"] for c in repo.listar_categorias()]
    prompt = (f"CATEGORIAS EXISTENTES: {', '.join(existentes) if existentes else '(nenhuma ainda)'}\n\n"
              f"MEMÓRIA:\n{texto[:2000]}")
    try:
        r = llm.gerar_json(PROMPT_CATEGORIA, prompt, SugestaoCategoria)
    except Exception as e:  # noqa: BLE001 — sugestão é opcional: falhou, não sugere
        logger.warning("sugestão de categoria falhou: %s", e)
        return None
    # Nunca confiar cegamente na saída do LLM: o código confere e normaliza.
    nome = " ".join(r.categoria.strip().lower().split())[:40] or "geral"
    return {"categoria": nome, "nova": nome not in existentes, "motivo": r.motivo}

"""RAG: os dois fluxos do Lembra.

ALIMENTAR:  texto -> chunks -> embeddings -> banco (numa transação)
PERGUNTAR:  pergunta -> embedding -> busca (com filtro de categoria opcional)
            -> prompt com os trechos -> LLM -> resposta com fontes

R = Retrieval   : achar os chunks mais parecidos com a pergunta.
A = Augmented   : colar esses chunks no prompt, como "material de consulta".
G = Generation  : o LLM responde usando SÓ esse material.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .chunking import chunk_text
from .config import Settings, get_settings
from .embeddings import get_embedder
from .llm import get_llm
from .supabase import Trecho

SYSTEM_PROMPT = """Você é o Lembra, um assistente de organização pessoal que conhece a vida do usuário \
pelas memórias que ele mesmo registrou.

Regras:
- Responda usando APENAS as memórias fornecidas entre <memorias>. Não invente fatos.
- Ignore memórias que não tenham relação com a pergunta.
- Cite as memórias usadas no formato [1], [2]...
- Se as memórias não tiverem a resposta, diga claramente que não encontrou isso nas memórias.
- Fale com o usuário na segunda pessoa ("você"), em português do Brasil, de forma natural."""


class Repositorio(Protocol):
    def salvar_memoria(self, texto, categoria, data_evento, chunks, vetores) -> str: ...
    def buscar(self, vetor, k, categoria=None) -> list[Trecho]: ...


@dataclass
class Resposta:
    texto: str
    fontes: list[Trecho]


def alimentar(
    repo: Repositorio, texto: str, categoria: str = "geral", data_evento: str = "",
    settings: Settings | None = None,
) -> tuple[str, int]:
    """Quebra, gera embeddings e salva. Retorna (id da memória, número de chunks)."""
    s = settings or get_settings()
    chunks = chunk_text(texto, s.chunk_size, s.chunk_overlap)
    if not chunks:
        raise ValueError("A memória está vazia")
    vetores = get_embedder(s.embedding_model).embed_documents(chunks)
    return repo.salvar_memoria(texto, categoria, data_evento, chunks, vetores), len(chunks)


def buscar(
    repo: Repositorio, pergunta: str, categoria: str | None = None, settings: Settings | None = None
) -> list[Trecho]:
    """Retrieval: embedding da pergunta -> vizinhos mais próximos no banco."""
    s = settings or get_settings()
    vetor = get_embedder(s.embedding_model).embed_query(pergunta)
    return repo.buscar(vetor, s.top_k, categoria)


def montar_prompt(pergunta: str, trechos: list[Trecho]) -> str:
    """Augmentation: junta pergunta + trechos recuperados num único prompt."""
    blocos = []
    for i, t in enumerate(trechos, start=1):
        quando = f' data="{t.metadados["data"]}"' if t.metadados.get("data") else ""
        categoria = t.metadados.get("categoria", "geral")
        blocos.append(f'<memoria indice="{i}" categoria="{categoria}"{quando}>\n{t.texto}\n</memoria>')
    contexto = "\n".join(blocos) or "(nenhuma memória encontrada)"
    return f"<memorias>\n{contexto}\n</memorias>\n\nPergunta: {pergunta}"


def perguntar(
    repo: Repositorio, pergunta: str, categoria: str | None = None, settings: Settings | None = None
) -> Resposta:
    s = settings or get_settings()
    trechos = buscar(repo, pergunta, categoria, s)
    if not trechos:
        return Resposta("Ainda não encontrei memórias suas sobre isso. Registre algumas primeiro.", [])
    texto = get_llm(s).gerar(SYSTEM_PROMPT, montar_prompt(pergunta, trechos))
    return Resposta(texto, trechos)

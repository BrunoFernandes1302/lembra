"""RAG: o caminho "Perguntar" (pergunta -> busca -> prompt com contexto -> LLM).

R = Retrieval   : achar os chunks mais parecidos com a pergunta.
A = Augmented   : colar esses chunks no prompt, como "material de consulta".
G = Generation  : o LLM responde usando SÓ esse material.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings, get_settings
from .embeddings import get_embedder
from .llm import get_llm
from .store import Trecho, VectorStore

SYSTEM_PROMPT = """Você é o "segundo cérebro" do usuário: um assistente que conhece a vida dele \
pelas memórias que ele mesmo registrou.

Regras:
- Responda usando APENAS as memórias fornecidas entre <memorias>. Não invente fatos.
- Cite as memórias usadas no formato [1], [2]...
- Se as memórias não tiverem a resposta, diga claramente que não encontrou isso nas memórias.
- Fale com o usuário na segunda pessoa ("você"), em português do Brasil, de forma natural."""


@dataclass
class Resposta:
    texto: str
    fontes: list[Trecho]


def buscar(pergunta: str, settings: Settings | None = None) -> list[Trecho]:
    """Retrieval: embedding da pergunta -> vizinhos mais próximos no banco."""
    s = settings or get_settings()
    vetor = get_embedder(s.embedding_model).embed_query(pergunta)
    return VectorStore(s.chroma_dir).buscar(vetor, s.top_k)


def montar_prompt(pergunta: str, trechos: list[Trecho]) -> str:
    """Augmentation: junta pergunta + trechos recuperados num único prompt."""
    blocos = []
    for i, t in enumerate(trechos, start=1):
        quando = f' data="{t.metadados["data"]}"' if t.metadados.get("data") else ""
        categoria = t.metadados.get("categoria", "geral")
        blocos.append(f'<memoria indice="{i}" categoria="{categoria}"{quando}>\n{t.texto}\n</memoria>')
    contexto = "\n".join(blocos) or "(nenhuma memória encontrada)"
    return f"<memorias>\n{contexto}\n</memorias>\n\nPergunta: {pergunta}"


def perguntar(pergunta: str, settings: Settings | None = None) -> Resposta:
    s = settings or get_settings()
    trechos = buscar(pergunta, s)
    if not trechos:
        return Resposta("Ainda não há memórias cadastradas. Alimente o cérebro primeiro.", [])
    texto = get_llm(s).gerar(SYSTEM_PROMPT, montar_prompt(pergunta, trechos))
    return Resposta(texto, trechos)

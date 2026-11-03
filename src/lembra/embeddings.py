"""Embeddings: transformar texto em vetor (lista de números) que representa o SIGNIFICADO.

Textos com sentidos parecidos geram vetores próximos, mesmo com palavras diferentes.

Dois provedores (EMBEDDING_PROVIDER no .env):
  * "gemini" (padrão) -> gemini-embedding-001 via API do Google. Leve para o servidor (cabe na
                         Vercel) e separou melhor o relevante do irrelevante nos nossos testes.
                         Atenção: o texto de TODAS as memórias passa pelo Google ao salvar.
  * "local"           -> multilingual-e5-small rodando no próprio servidor (privado, mas
                         exige ~1 GB de RAM). Instale com:  pip install -e ".[local]"

IMPORTANTE: vetores de modelos diferentes vivem em "mapas" diferentes e não podem ser
comparados. Por isso cada chunk guarda o nome do modelo que o gerou, e a busca só compara
vetores do mesmo modelo. Trocar de modelo exige reprocessar as memórias.

Os dois modelos distinguem "texto guardado" de "pergunta":
  * Gemini: task_type RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY
  * E5: prefixos "passage: " / "query: "
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Protocol


class Embedder(Protocol):
    modelo: str

    def embed_documents(self, textos: list[str]) -> list[list[float]]: ...
    def embed_query(self, pergunta: str) -> list[float]: ...


def _normalizar(v: list[float]) -> list[float]:
    # Vetor de tamanho 1: a similaridade de cosseno fica comparável entre textos.
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class GeminiEmbedder:
    LOTE = 100  # a API aceita vários textos por chamada; mandamos em lotes

    def __init__(self, modelo: str, api_key: str, dimensao: int):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.modelo = modelo
        self.dimensao = dimensao

    def _embed(self, textos: list[str], tarefa: str) -> list[list[float]]:
        from google.genai import types

        vetores: list[list[float]] = []
        for i in range(0, len(textos), self.LOTE):
            r = self.client.models.embed_content(
                model=self.modelo,
                contents=textos[i : i + self.LOTE],
                config=types.EmbedContentConfig(task_type=tarefa, output_dimensionality=self.dimensao),
            )
            vetores.extend(_normalizar(list(e.values)) for e in r.embeddings)
        return vetores

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        return self._embed(textos, "RETRIEVAL_DOCUMENT")

    def embed_query(self, pergunta: str) -> list[float]:
        return self._embed([pergunta], "RETRIEVAL_QUERY")[0]


class LocalEmbedder:
    def __init__(self, modelo: str):
        from sentence_transformers import SentenceTransformer  # import pesado, só quando usar

        self.modelo = modelo
        self.model = SentenceTransformer(modelo)
        self._prefixo_e5 = "e5" in modelo.lower()

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        if self._prefixo_e5:
            textos = [f"passage: {t}" for t in textos]
        return self.model.encode(textos, normalize_embeddings=True).tolist()

    def embed_query(self, pergunta: str) -> list[float]:
        if self._prefixo_e5:
            pergunta = f"query: {pergunta}"
        return self.model.encode([pergunta], normalize_embeddings=True).tolist()[0]


@lru_cache
def get_embedder(provedor: str, modelo: str, api_key: str = "", dimensao: int = 768) -> Embedder:
    """Cria o embedder uma vez por processo (carregar o modelo local é lento)."""
    if provedor == "gemini":
        return GeminiEmbedder(modelo, api_key, dimensao)
    if provedor == "local":
        return LocalEmbedder(modelo)
    raise ValueError(f"EMBEDDING_PROVIDER desconhecido: {provedor!r}")

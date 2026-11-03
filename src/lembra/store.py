"""Banco vetorial: guarda (chunk, vetor, metadados) e encontra os vetores mais próximos.

ChromaDB em modo local (arquivos em data/chroma). Em produção a mesma ideia roda em
pgvector (Postgres), Qdrant, Weaviate etc.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import chromadb

COLECAO = "memorias"


@dataclass
class Trecho:
    """Um chunk recuperado pela busca."""

    texto: str
    metadados: dict
    distancia: float  # distância de cosseno: 0 = idêntico

    @property
    def similaridade(self) -> float:
        return 1 - self.distancia


class VectorStore:
    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.colecao = self._abrir()

    def _abrir(self):
        return self.client.get_or_create_collection(
            name=COLECAO, metadata={"hnsw:space": "cosine"}
        )

    def adicionar(self, ids, textos, vetores, metadados) -> None:
        self.colecao.upsert(ids=ids, documents=textos, embeddings=vetores, metadatas=metadados)

    def buscar(self, vetor: list[float], k: int) -> list[Trecho]:
        total = self.colecao.count()
        if total == 0:
            return []
        res = self.colecao.query(query_embeddings=[vetor], n_results=min(k, total))
        return [
            Trecho(texto=doc, metadados=meta or {}, distancia=dist)
            for doc, meta, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    def total(self) -> int:
        return self.colecao.count()

    def limpar(self) -> None:
        self.client.delete_collection(COLECAO)
        self.colecao = self._abrir()

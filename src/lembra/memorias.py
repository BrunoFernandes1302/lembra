"""Ingestão: o caminho "Alimentar" (texto -> chunks -> embeddings -> banco vetorial).

Duas camadas de armazenamento, de propósito:
  * data/memorias.jsonl -> FONTE DA VERDADE. Texto original, legível, fácil de fazer backup.
  * data/chroma/        -> ÍNDICE. Derivado da fonte; pode ser apagado e reconstruído.

Assim, se você trocar o modelo de embeddings ou o tamanho do chunk, basta `reindexar()`.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime

from .chunking import chunk_text
from .config import Settings, get_settings
from .embeddings import get_embedder
from .store import VectorStore


@dataclass
class Memoria:
    texto: str
    categoria: str = "geral"
    data: str = ""  # quando aconteceu (texto livre: "2020", "março de 2018"...)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    criado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def salvar(memoria: Memoria, settings: Settings | None = None) -> int:
    """Grava a memória na fonte da verdade e indexa. Retorna quantos chunks gerou."""
    s = settings or get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    with s.memorias_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(memoria), ensure_ascii=False) + "\n")
    return _indexar([memoria], s, VectorStore(s.chroma_dir))


def listar(settings: Settings | None = None) -> list[Memoria]:
    s = settings or get_settings()
    if not s.memorias_file.exists():
        return []
    with s.memorias_file.open(encoding="utf-8") as f:
        return [Memoria(**json.loads(linha)) for linha in f if linha.strip()]


def reindexar(settings: Settings | None = None) -> int:
    """Apaga o índice e reconstrói tudo a partir de memorias.jsonl."""
    s = settings or get_settings()
    store = VectorStore(s.chroma_dir)
    store.limpar()
    return _indexar(listar(s), s, store)


def _indexar(memorias: list[Memoria], s: Settings, store: VectorStore) -> int:
    ids, textos, metadados = [], [], []
    for m in memorias:
        for i, chunk in enumerate(chunk_text(m.texto, s.chunk_size, s.chunk_overlap)):
            ids.append(f"{m.id}-{i}")
            textos.append(chunk)
            # Metadados viajam junto com o chunk: servem para citar a fonte e filtrar.
            metadados.append(
                {"memoria_id": m.id, "categoria": m.categoria, "data": m.data, "chunk": i}
            )
    if textos:
        vetores = get_embedder(s.embedding_model).embed_documents(textos)
        store.adicionar(ids, textos, vetores, metadados)
    return len(textos)

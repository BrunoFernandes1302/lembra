"""Configuração central, lida do arquivo .env (veja .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    llm_provider: str
    anthropic_model: str
    anthropic_effort: str
    ollama_model: str
    ollama_url: str

    @property
    def memorias_file(self) -> Path:
        """Fonte da verdade: todas as memórias em texto puro (uma por linha, JSON)."""
        return self.data_dir / "memorias.jsonl"

    @property
    def chroma_dir(self) -> Path:
        """Índice vetorial — pode ser apagado e reconstruído a partir de memorias.jsonl."""
        return self.data_dir / "chroma"


@lru_cache
def get_settings() -> Settings:
    return Settings(
        data_dir=Path(os.getenv("DATA_DIR", "data")),
        embedding_model=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        chunk_size=int(os.getenv("CHUNK_SIZE", "800")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
        top_k=int(os.getenv("TOP_K", "5")),
        llm_provider=os.getenv("LLM_PROVIDER", "anthropic").lower(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=os.getenv("ANTHROPIC_EFFORT", "medium"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
    )

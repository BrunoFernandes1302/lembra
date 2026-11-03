"""Configuração central, lida do arquivo .env (veja .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    embedding_provider: str
    embedding_model: str
    embedding_dim: int
    chunk_size: int
    chunk_overlap: int
    top_k: int
    margem_relevancia: float
    usar_ia: bool
    instrucoes: str
    llm_provider: str
    anthropic_model: str
    anthropic_effort: str
    ollama_model: str
    gemini_model: str
    gemini_api_key: str
    ollama_url: str
    supabase_url: str
    supabase_key: str


@lru_cache
def get_settings() -> Settings:
    return Settings(
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "gemini").lower(),
        embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"),
        embedding_dim=int(os.getenv("EMBEDDING_DIM", "768")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "800")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
        top_k=int(os.getenv("TOP_K", "5")),
        margem_relevancia=float(os.getenv("MARGEM_RELEVANCIA", "0.05")),
        usar_ia=True,
        instrucoes="",
        llm_provider=os.getenv("LLM_PROVIDER", "nenhum").lower(),
        anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_effort=os.getenv("ANTHROPIC_EFFORT", "medium"),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        supabase_url=os.getenv("SUPABASE_URL", ""),
        supabase_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
    )


def embedder_de(s: Settings):
    """Atalho: o embedder configurado."""
    from .embeddings import get_embedder

    return get_embedder(s.embedding_provider, s.embedding_model, s.gemini_api_key, s.embedding_dim)


# Campos que cada usuário pode ajustar no app (tabela config_rag) e o campo correspondente aqui.
CAMPOS_DO_USUARIO = {
    "chunk_size": "chunk_size",
    "chunk_overlap": "chunk_overlap",
    "top_k": "top_k",
    "margem_relevancia": "margem_relevancia",
    "usar_ia": "usar_ia",
    "modelo_llm": "gemini_model",
    "instrucoes": "instrucoes",
}


def com_config_do_usuario(s: Settings, cfg: dict | None) -> Settings:
    """Padrões do servidor + o que o usuário configurou (se configurou)."""
    if not cfg:
        return s
    return replace(s, **{campo: cfg[col] for col, campo in CAMPOS_DO_USUARIO.items() if col in cfg})

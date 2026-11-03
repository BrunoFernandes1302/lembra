"""Configuração central, lida do arquivo .env (veja .env.example)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
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
        embedding_model=os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small"),
        chunk_size=int(os.getenv("CHUNK_SIZE", "800")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "150")),
        top_k=int(os.getenv("TOP_K", "5")),
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

"""LLM: o modelo que escreve a resposta final (o "G" de RAG, de Generation).

Dois provedores atrás da mesma interface `gerar(system, prompt) -> str`:
  * ClaudeLLM  -> API da Anthropic (os chunks recuperados SÃO enviados para a API).
  * OllamaLLM  -> modelo rodando na sua máquina (100% local).
Trocar um pelo outro é só mudar LLM_PROVIDER no .env.
"""

from __future__ import annotations

from typing import Protocol

from .config import Settings, get_settings


class LLM(Protocol):
    def gerar(self, system: str, prompt: str) -> str: ...


class ClaudeLLM:
    def __init__(self, model: str, effort: str):
        import anthropic

        self.client = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do ambiente
        self.model = model
        self.effort = effort

    def gerar(self, system: str, prompt: str) -> str:
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
            # effort: quanto o modelo "pensa" antes de responder (low ... max).
            output_config={"effort": self.effort},
            # Se o modelo recusar por política de segurança, a API tenta outro modelo.
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
        if response.stop_reason == "refusal":
            return "O modelo se recusou a responder essa pergunta."
        return "".join(b.text for b in response.content if b.type == "text").strip()


class OllamaLLM:
    def __init__(self, model: str, url: str):
        self.model = model
        self.url = url.rstrip("/")

    def gerar(self, system: str, prompt: str) -> str:
        import requests

        r = requests.post(
            f"{self.url}/api/chat",
            json={
                "model": self.model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=300,
        )
        r.raise_for_status()
        return r.json()["message"]["content"].strip()


def get_llm(settings: Settings | None = None) -> LLM:
    s = settings or get_settings()
    if s.llm_provider == "anthropic":
        return ClaudeLLM(s.anthropic_model, s.anthropic_effort)
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_model, s.ollama_url)
    raise ValueError(f"LLM_PROVIDER desconhecido: {s.llm_provider!r}")

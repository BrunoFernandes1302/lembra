"""LLM: o modelo que escreve a resposta final (o "G" de RAG, de Generation).

Provedores atrás da mesma interface `gerar(system, prompt) -> str`
(trocar é só mudar LLM_PROVIDER no .env):
  * "gemini"    -> API do Google. Tem nível GRATUITO, mas nele o Google pode usar os dados
                   enviados (trechos + pergunta) para melhorar produtos e pessoas podem lê-los.
  * "anthropic" -> API do Claude (paga por uso; não usa os dados para treino).
  * "ollama"    -> modelo rodando na sua máquina (grátis e 100% local).
  * "nenhum"    -> sem geração: o app só mostra as memórias encontradas.
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


class GeminiLLM:
    def __init__(self, model: str, api_key: str):
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def gerar(self, system: str, prompt: str) -> str:
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return (response.text or "").strip()

    def transcrever(self, audio: bytes, mime: str) -> str:
        """Modelo MULTIMODAL: o Gemini recebe o áudio e devolve o texto (speech-to-text)."""
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Part.from_bytes(data=audio, mime_type=mime),
                      ("Transcreva fielmente este áudio em português do Brasil, com pontuação. "
                       "Responda só com a transcrição. Se não houver fala, responda vazio.")],
            config=types.GenerateContentConfig(temperature=0),
        )
        return (response.text or "").strip()

    def gerar_json(self, system: str, prompt: str, esquema):
        """SAÍDA ESTRUTURADA: o modelo é obrigado a responder no formato do esquema (Pydantic).
        Nada de texto solto para "decifrar" depois."""
        from google.genai import types

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system, temperature=0,
                response_mime_type="application/json", response_schema=esquema),
        )
        if isinstance(response.parsed, esquema):
            return response.parsed
        return esquema.model_validate_json(response.text)


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


def get_llm(settings: Settings | None = None) -> LLM | None:
    """Devolve o LLM configurado, ou None no modo "nenhum" (só busca, sem geração)."""
    s = settings or get_settings()
    if s.llm_provider == "nenhum":
        return None
    if s.llm_provider == "gemini":
        return GeminiLLM(s.gemini_model, s.gemini_api_key)
    if s.llm_provider == "anthropic":
        return ClaudeLLM(s.anthropic_model, s.anthropic_effort)
    if s.llm_provider == "ollama":
        return OllamaLLM(s.ollama_model, s.ollama_url)
    raise ValueError(f"LLM_PROVIDER desconhecido: {s.llm_provider!r}")

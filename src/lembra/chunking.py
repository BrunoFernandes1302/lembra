"""Chunking: quebrar textos longos em pedaços menores ("chunks").

Por quê? O modelo de embeddings resume um texto inteiro em UM vetor. Se o texto mistura
vários assuntos, o vetor vira uma "média" deles e a busca perde precisão.

Estratégia recursiva: tenta quebrar por parágrafo; se o pedaço ainda for grande, por linha,
depois frase, depois palavra. Em seguida junta pedaços vizinhos até perto de `chunk_size`,
repetindo um trecho (`overlap`) entre chunks para não perder contexto na fronteira.
"""

from __future__ import annotations

import re

SEPARADORES = ["\n\n", "\n", ". ", " "]


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    if chunk_size <= 0:
        raise ValueError("chunk_size deve ser > 0")
    if not 0 <= overlap < chunk_size:
        raise ValueError("overlap deve estar entre 0 e chunk_size - 1")

    text = _normalizar(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    return _juntar(_dividir(text, chunk_size, SEPARADORES), chunk_size, overlap)


def _normalizar(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dividir(text: str, chunk_size: int, separadores: list[str]) -> list[str]:
    """Quebra recursivamente até todo pedaço caber em `chunk_size`."""
    if len(text) <= chunk_size:
        return [text]
    if not separadores:  # último recurso: corte bruto
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]

    sep, resto = separadores[0], separadores[1:]
    if sep not in text:
        return _dividir(text, chunk_size, resto)

    partes = text.split(sep)
    saida: list[str] = []
    for i, parte in enumerate(partes):
        if i < len(partes) - 1:
            parte += sep
        if parte:
            saida.extend(_dividir(parte, chunk_size, resto))
    return saida


def _juntar(pedacos: list[str], chunk_size: int, overlap: int) -> list[str]:
    """Agrupa pedaços pequenos em chunks, mantendo até `overlap` caracteres entre vizinhos."""
    chunks: list[str] = []
    atual: list[str] = []
    tamanho = 0
    for p in pedacos:
        if atual and tamanho + len(p) > chunk_size:
            chunks.append("".join(atual).strip())
            while atual and (tamanho > overlap or tamanho + len(p) > chunk_size):
                tamanho -= len(atual.pop(0))
        atual.append(p)
        tamanho += len(p)
    if atual:
        chunks.append("".join(atual).strip())
    return [c for c in chunks if c]

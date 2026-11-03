"""Embeddings: transformar texto em vetor (lista de números) que representa o SIGNIFICADO.

Textos com sentidos parecidos geram vetores próximos, mesmo com palavras diferentes.
Roda localmente com `sentence-transformers` (sem custo, sem enviar dados para fora).

O modelo padrão (família E5, multilíngue) foi treinado com prefixos: "passage: " para
textos guardados e "query: " para perguntas. Usar os prefixos melhora a busca.
"""

from __future__ import annotations

from functools import lru_cache


class Embedder:
    def __init__(self, model_name: str):
        from sentence_transformers import SentenceTransformer  # import pesado, só quando usar

        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        self._prefixo_e5 = "e5" in model_name.lower()

    def embed_documents(self, textos: list[str]) -> list[list[float]]:
        if self._prefixo_e5:
            textos = [f"passage: {t}" for t in textos]
        return self._encode(textos)

    def embed_query(self, pergunta: str) -> list[float]:
        if self._prefixo_e5:
            pergunta = f"query: {pergunta}"
        return self._encode([pergunta])[0]

    def _encode(self, textos: list[str]) -> list[list[float]]:
        # Vetores normalizados (tamanho 1): similaridade de cosseno vira produto escalar.
        return self.model.encode(textos, normalize_embeddings=True).tolist()


@lru_cache
def get_embedder(model_name: str) -> Embedder:
    """Carrega o modelo uma vez por processo (carregar é lento)."""
    return Embedder(model_name)

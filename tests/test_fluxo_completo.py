"""Teste do encanamento: salvar -> indexar -> buscar -> montar prompt -> LLM.

Usa um embedder e um LLM FALSOS para rodar sem internet e sem custo. Valida que as peças
se conectam corretamente, NÃO a qualidade da busca semântica (isso exige o modelo real).
"""

import hashlib
import math

import pytest

from segundo_cerebro import memorias, rag
from segundo_cerebro.config import Settings


class EmbedderFalso:
    """Vetor = contagem de palavras (bag-of-words com hash). Só acha palavras iguais."""

    def _vet(self, texto):
        v = [0.0] * 64
        for p in texto.lower().split():
            v[int(hashlib.md5(p.strip(".,?!").encode()).hexdigest(), 16) % 64] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]

    def embed_documents(self, textos):
        return [self._vet(t) for t in textos]

    def embed_query(self, t):
        return self._vet(t)


class LLMFalso:
    def gerar(self, system, prompt):
        self.prompt = prompt
        return "resposta falsa [1]"


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = Settings(
        data_dir=tmp_path, embedding_model="falso", chunk_size=200, chunk_overlap=20, top_k=2,
        llm_provider="falso", anthropic_model="", anthropic_effort="", ollama_model="", ollama_url="",
    )
    monkeypatch.setattr(memorias, "get_embedder", lambda _: EmbedderFalso())
    monkeypatch.setattr(rag, "get_embedder", lambda _: EmbedderFalso())
    return s


def test_salvar_buscar_perguntar(settings, monkeypatch):
    memorias.salvar(memorias.Memoria("Minha cachorra se chama Mel.", "família", "2020"), settings)
    memorias.salvar(memorias.Memoria("Viajei para o Chile em 2019.", "viagens"), settings)

    trechos = rag.buscar("como se chama minha cachorra?", settings)
    assert trechos[0].texto == "Minha cachorra se chama Mel."
    assert trechos[0].metadados["categoria"] == "família"

    llm = LLMFalso()
    monkeypatch.setattr(rag, "get_llm", lambda _: llm)
    r = rag.perguntar("como se chama minha cachorra?", settings)
    assert r.texto == "resposta falsa [1]"
    assert "Mel" in llm.prompt


def test_reindexar_reconstroi_a_partir_do_jsonl(settings):
    memorias.salvar(memorias.Memoria("Texto um."), settings)
    memorias.salvar(memorias.Memoria("Texto dois."), settings)
    assert memorias.reindexar(settings) == 2
    assert len(memorias.listar(settings)) == 2

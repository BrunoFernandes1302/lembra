"""Fluxo completo pela API: alimentar -> listar -> buscar -> perguntar -> apagar.

Usa um banco, um embedder e um LLM FALSOS para rodar sem internet e sem custo. Valida que as
peças se conectam, NÃO a qualidade da busca semântica (isso exige o modelo real).
O banco falso imita o RLS: cada crachá (token) só enxerga o que é seu.
"""

import hashlib
import math
import uuid

import pytest
from fastapi.testclient import TestClient

from lembra import api, rag
from lembra.supabase import Trecho


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
        LLMFalso.ultimo_prompt = prompt
        return "resposta falsa [1]"


BANCO = {"memorias": [], "chunks": []}


class RepoFalso:
    def __init__(self, token):
        self.dono = token  # no banco falso, o próprio token identifica o dono

    def salvar_memoria(self, texto, categoria, data_evento, chunks, vetores):
        mid = str(uuid.uuid4())
        BANCO["memorias"].append({"id": mid, "dono": self.dono, "texto": texto,
                                  "categoria": categoria, "data_evento": data_evento})
        for t, v in zip(chunks, vetores):
            BANCO["chunks"].append({"memoria_id": mid, "dono": self.dono, "texto": t,
                                    "categoria": categoria, "data": data_evento, "v": v})
        return mid

    def listar_memorias(self, categoria=None, limite=50):
        return [m for m in BANCO["memorias"] if m["dono"] == self.dono
                and (categoria is None or m["categoria"] == categoria)]

    def apagar_memoria(self, mid):
        antes = len(BANCO["memorias"])
        BANCO["memorias"] = [m for m in BANCO["memorias"] if not (m["id"] == mid and m["dono"] == self.dono)]
        BANCO["chunks"] = [c for c in BANCO["chunks"] if not (c["memoria_id"] == mid and c["dono"] == self.dono)]
        return len(BANCO["memorias"]) < antes

    def buscar(self, vetor, k, categoria=None):
        meus = [c for c in BANCO["chunks"] if c["dono"] == self.dono
                and (categoria is None or c["categoria"] == categoria)]
        ordenados = sorted(meus, key=lambda c: -sum(a * b for a, b in zip(c["v"], vetor)))[:k]
        return [Trecho(c["texto"], {"memoria_id": c["memoria_id"], "categoria": c["categoria"],
                                    "data": c["data"]}, sum(a * b for a, b in zip(c["v"], vetor)))
                for c in ordenados]


@pytest.fixture
def cliente(monkeypatch):
    BANCO["memorias"].clear()
    BANCO["chunks"].clear()
    monkeypatch.setattr(rag, "get_embedder", lambda _: EmbedderFalso())
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMFalso())
    api.app.dependency_overrides[api.repositorio] = lambda cred=api.Depends(api._bearer): RepoFalso(cred.credentials)
    yield TestClient(api.app)
    api.app.dependency_overrides.clear()


ANA = {"Authorization": "Bearer token-da-ana"}
BETO = {"Authorization": "Bearer token-do-beto"}


def test_sem_cracha_e_recusado(cliente):
    assert cliente.get("/memorias").status_code in (401, 403)


def test_fluxo_completo(cliente):
    r = cliente.post("/memorias", headers=ANA, json={"texto": "Minha cachorra se chama Mel.",
                                                     "categoria": "família", "data_evento": "2020"})
    assert r.status_code == 201 and r.json()["chunks"] == 1
    cliente.post("/memorias", headers=ANA, json={"texto": "Gastei 300 reais no mercado.", "categoria": "finanças"})

    assert len(cliente.get("/memorias", headers=ANA).json()) == 2
    assert len(cliente.get("/memorias?categoria=finanças", headers=ANA).json()) == 1

    fontes = cliente.post("/buscar", headers=ANA, json={"pergunta": "como se chama minha cachorra?"}).json()
    assert fontes[0]["texto"] == "Minha cachorra se chama Mel."

    so_financas = cliente.post("/buscar", headers=ANA,
                               json={"pergunta": "como se chama minha cachorra?", "categoria": "finanças"}).json()
    assert [f["categoria"] for f in so_financas] == ["finanças"]

    r = cliente.post("/perguntar", headers=ANA, json={"pergunta": "como se chama minha cachorra?"}).json()
    assert r["resposta"] == "resposta falsa [1]"
    assert "Mel" in LLMFalso.ultimo_prompt


def test_isolamento_entre_usuarios(cliente):
    mid = cliente.post("/memorias", headers=ANA, json={"texto": "Segredo da Ana."}).json()["id"]
    assert cliente.get("/memorias", headers=BETO).json() == []
    assert cliente.post("/buscar", headers=BETO, json={"pergunta": "segredo"}).json() == []
    assert cliente.delete(f"/memorias/{mid}", headers=BETO).status_code == 404
    assert cliente.delete(f"/memorias/{mid}", headers=ANA).status_code == 204


def test_memoria_vazia_e_rejeitada(cliente):
    assert cliente.post("/memorias", headers=ANA, json={"texto": ""}).status_code == 422
    assert cliente.post("/memorias", headers=ANA, json={"texto": "   \n  "}).status_code == 400


def test_modo_sem_ia_mostra_so_as_memorias(cliente, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda _: None)
    cliente.post("/memorias", headers=ANA, json={"texto": "Minha cachorra se chama Mel."})
    r = cliente.post("/perguntar", headers=ANA, json={"pergunta": "nome da cachorra"}).json()
    assert r["gerada_por_ia"] is False
    assert r["fontes"][0]["texto"] == "Minha cachorra se chama Mel."


def test_falha_do_llm_nao_derruba_o_app(cliente, monkeypatch):
    class LLMQuebrado:
        def gerar(self, system, prompt):
            raise RuntimeError("429 limite diário atingido")

    monkeypatch.setattr(rag, "get_llm", lambda _: LLMQuebrado())
    cliente.post("/memorias", headers=ANA, json={"texto": "Minha cachorra se chama Mel."})
    r = cliente.post("/perguntar", headers=ANA, json={"pergunta": "nome da cachorra"})
    assert r.status_code == 200
    assert r.json()["gerada_por_ia"] is False and "Não consegui" in r.json()["resposta"]
    assert len(r.json()["fontes"]) == 1

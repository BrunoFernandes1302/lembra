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

    chamadas = 0  # quantas vezes gerou vetores de documentos (para provar quando NÃO recalcula)

    def _vet(self, texto):
        v = [0.0] * 64
        for p in texto.lower().split():
            v[int(hashlib.md5(p.strip(".,?!").encode()).hexdigest(), 16) % 64] += 1
        n = math.sqrt(sum(x * x for x in v)) or 1
        return [x / n for x in v]

    def embed_documents(self, textos):
        EmbedderFalso.chamadas += 1
        return [self._vet(t) for t in textos]

    def embed_query(self, t):
        return self._vet(t)


class LLMFalso:
    def gerar(self, system, prompt):
        LLMFalso.ultimo_prompt = prompt
        return "resposta falsa [1]"


BANCO = {"memorias": [], "chunks": [], "categorias": []}
PADRAO = ["geral", "família", "finanças", "compromissos"]


class RepoFalso:
    def __init__(self, token):
        self.dono = token  # no banco falso, o próprio token identifica o dono

    def salvar_memoria(self, texto, categoria, data_evento, chunks, vetores, modelo):
        mid = str(uuid.uuid4())
        BANCO["memorias"].append({"id": mid, "dono": self.dono, "texto": texto,
                                  "categoria": categoria, "data_evento": data_evento})
        for t, v in zip(chunks, vetores):
            BANCO["chunks"].append({"memoria_id": mid, "dono": self.dono, "texto": t,
                                    "categoria": categoria, "data": data_evento, "v": v})
        return mid

    def obter_memoria(self, mid):
        return next((m for m in BANCO["memorias"] if m["id"] == mid and m["dono"] == self.dono), None)

    def atualizar_memoria(self, mid, texto, categoria, data_evento, chunks=None, vetores=None, modelo=None):
        m = self.obter_memoria(mid)
        if not m:
            return False
        self.criar_categoria(categoria)
        m.update(texto=texto, categoria=categoria, data_evento=data_evento)
        if chunks is not None:
            BANCO["chunks"] = [c for c in BANCO["chunks"] if c["memoria_id"] != mid]
            for t, v in zip(chunks, vetores):
                BANCO["chunks"].append({"memoria_id": mid, "dono": self.dono, "texto": t,
                                        "categoria": categoria, "data": data_evento, "v": v})
        else:
            for c in BANCO["chunks"]:
                if c["memoria_id"] == mid:
                    c["categoria"] = categoria
        return True

    def _minhas_cats(self):
        if not any(c["dono"] == self.dono for c in BANCO["categorias"]):
            BANCO["categorias"].extend({"dono": self.dono, "nome": n} for n in PADRAO)
        return [c for c in BANCO["categorias"] if c["dono"] == self.dono]

    def listar_categorias(self):
        return [{"nome": c["nome"], "memorias": sum(1 for m in BANCO["memorias"]
                 if m["dono"] == self.dono and m["categoria"] == c["nome"])} for c in self._minhas_cats()]

    def criar_categoria(self, nome):
        if nome not in [c["nome"] for c in self._minhas_cats()]:
            BANCO["categorias"].append({"dono": self.dono, "nome": nome})

    def _mover(self, de, para):
        n = 0
        for x in BANCO["memorias"] + BANCO["chunks"]:
            if x["dono"] == self.dono and x["categoria"] == de:
                x["categoria"] = para
                n += "id" in x
        BANCO["categorias"] = [c for c in BANCO["categorias"] if not (c["dono"] == self.dono and c["nome"] == de)]
        return n

    def renomear_categoria(self, antigo, novo):
        self.criar_categoria(novo)
        self._mover(antigo, novo)

    def apagar_categoria(self, nome, mover_para="geral"):
        self.criar_categoria(mover_para)
        return self._mover(nome, mover_para)

    def listar_memorias(self, categoria=None, limite=50):
        return [m for m in BANCO["memorias"] if m["dono"] == self.dono
                and (categoria is None or m["categoria"] == categoria)]

    def apagar_memoria(self, mid):
        antes = len(BANCO["memorias"])
        BANCO["memorias"] = [m for m in BANCO["memorias"] if not (m["id"] == mid and m["dono"] == self.dono)]
        BANCO["chunks"] = [c for c in BANCO["chunks"] if not (c["memoria_id"] == mid and c["dono"] == self.dono)]
        return len(BANCO["memorias"]) < antes

    def buscar(self, vetor, k, categoria=None, modelo=None):
        meus = [c for c in BANCO["chunks"] if c["dono"] == self.dono
                and (categoria is None or c["categoria"] == categoria)]
        ordenados = sorted(meus, key=lambda c: -sum(a * b for a, b in zip(c["v"], vetor)))[:k]
        return [Trecho(c["texto"], {"memoria_id": c["memoria_id"], "categoria": c["categoria"],
                                    "data": c["data"]}, sum(a * b for a, b in zip(c["v"], vetor)))
                for c in ordenados]


@pytest.fixture
def cliente(monkeypatch):
    for v in BANCO.values():
        v.clear()
    monkeypatch.setattr(rag, "embedder_de", lambda _: EmbedderFalso())
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


def test_editar_so_categoria_nao_recalcula_vetores(cliente):
    mid = cliente.post("/memorias", headers=ANA, json={"texto": "Gastei 300 no mercado.", "categoria": "geral"}).json()["id"]
    antes = EmbedderFalso.chamadas
    r = cliente.put(f"/memorias/{mid}", headers=ANA, json={"texto": "Gastei 300 no mercado.", "categoria": "finanças"})
    assert r.json()["recalculou"] is False and EmbedderFalso.chamadas == antes
    so_fin = cliente.post("/buscar", headers=ANA, json={"pergunta": "mercado", "categoria": "finanças"}).json()
    assert len(so_fin) == 1, "o chunk precisa mudar de categoria junto com a memória"


def test_editar_texto_recalcula_vetores(cliente):
    mid = cliente.post("/memorias", headers=ANA, json={"texto": "Minha cachorra se chama Mel."}).json()["id"]
    r = cliente.put(f"/memorias/{mid}", headers=ANA, json={"texto": "Minha gata se chama Luna.", "categoria": "família"})
    assert r.json()["recalculou"] is True
    assert cliente.post("/buscar", headers=ANA, json={"pergunta": "gata Luna"}).json()[0]["texto"] == "Minha gata se chama Luna."


def test_beto_nao_edita_memoria_da_ana(cliente):
    mid = cliente.post("/memorias", headers=ANA, json={"texto": "Segredo da Ana."}).json()["id"]
    assert cliente.put(f"/memorias/{mid}", headers=BETO, json={"texto": "hackeado"}).status_code == 404


def test_categorias_criar_renomear_apagar_move_memorias(cliente):
    assert "família" in [c["nome"] for c in cliente.get("/categorias", headers=ANA).json()]
    cliente.post("/categorias", headers=ANA, json={"nome": "Pets"})
    cliente.post("/memorias", headers=ANA, json={"texto": "Mel é minha cachorra.", "categoria": "pets"})
    cliente.put("/categorias/pets", headers=ANA, json={"novo_nome": "animais"})
    cats = {c["nome"]: c["memorias"] for c in cliente.get("/categorias", headers=ANA).json()}
    assert "pets" not in cats and cats["animais"] == 1
    r = cliente.delete("/categorias/animais?mover_para=família", headers=ANA).json()
    assert r["memorias_movidas"] == 1
    assert cliente.get("/memorias?categoria=família", headers=ANA).json()[0]["texto"] == "Mel é minha cachorra."

"""Fluxo completo pela API: alimentar -> listar -> buscar -> perguntar -> apagar.

Usa um banco, um embedder e um LLM FALSOS para rodar sem internet e sem custo. Valida que as
peças se conectam, NÃO a qualidade da busca semântica (isso exige o modelo real).
O banco falso imita o RLS: cada crachá (token) só enxerga o que é seu.
"""

import hashlib
import math
import uuid

import pytest
from fastapi import Depends
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
        LLMFalso.ultimo_system = system
        LLMFalso.ultimo_prompt = prompt
        return "resposta falsa [1]"


BANCO = {"memorias": [], "chunks": [], "categorias": [], "config": [], "feedback": []}
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

    def obter_config(self):
        return next((c["cfg"] for c in BANCO["config"] if c["dono"] == self.dono), None)

    def salvar_config(self, cfg):
        BANCO["config"] = [c for c in BANCO["config"] if c["dono"] != self.dono] + [{"dono": self.dono, "cfg": cfg}]
        return cfg

    def registrar_feedback(self, pergunta, resposta, util, comentario):
        BANCO["feedback"].append({"dono": self.dono, "pergunta": pergunta, "resposta": resposta, "util": util,
                                  "comentario": comentario, "criado_em": str(len(BANCO["feedback"])).zfill(6)})

    def listar_feedback(self, limite=20, desde=None):
        meus = [f for f in BANCO["feedback"] if f["dono"] == self.dono and (desde is None or f["criado_em"] > desde)]
        return list(reversed(meus))[:limite]

    def salvar_perfil(self, perfil):
        cfg = dict(self.obter_config() or {})
        cfg.update(perfil_estilo=perfil, perfil_atualizado_em=str(len(BANCO["feedback"])).zfill(6))
        self.salvar_config(cfg)

    def listar_chunks(self, mid):
        return [{"indice": i, "texto": c["texto"]} for i, c in
                enumerate(c for c in BANCO["chunks"] if c["memoria_id"] == mid and c["dono"] == self.dono)]

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
    def repo_falso(cred=Depends(api._bearer)):
        return RepoFalso(cred.credentials)

    api.app.dependency_overrides[api.repositorio] = repo_falso
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


CFG = {"chunk_size": 800, "chunk_overlap": 150, "top_k": 5, "margem_relevancia": 0.05,
       "usar_ia": True, "modelo_llm": "gemini-flash-lite-latest", "instrucoes": "", "perfil_estilo": ""}


def test_config_padrao_e_salvar(cliente):
    assert cliente.get("/config", headers=ANA).json()["top_k"] == 5
    r = cliente.put("/config", headers=ANA, json={**CFG, "top_k": 2})
    assert r.status_code == 200
    assert cliente.get("/config", headers=ANA).json()["top_k"] == 2
    assert cliente.get("/config", headers=BETO).json()["top_k"] == 5, "config é por usuário"


def test_config_muda_o_comportamento(cliente):
    for i in range(4):
        cliente.post("/memorias", headers=ANA, json={"texto": f"Mercado semana {i} gastei pouco."})
    assert len(cliente.post("/buscar", headers=ANA, json={"pergunta": "mercado"}).json()) == 4
    cliente.put("/config", headers=ANA, json={**CFG, "top_k": 2, "instrucoes": "Responda em tópicos."})
    assert len(cliente.post("/buscar", headers=ANA, json={"pergunta": "mercado"}).json()) == 2
    cliente.post("/perguntar", headers=ANA, json={"pergunta": "mercado"})
    assert "Responda em tópicos." in LLMFalso.ultimo_system
    assert LLMFalso.ultimo_system.index("Regras") < LLMFalso.ultimo_system.index("Responda em tópicos.")


def test_desligar_ia_mostra_so_memorias(cliente):
    cliente.post("/memorias", headers=ANA, json={"texto": "Minha cachorra se chama Mel."})
    cliente.put("/config", headers=ANA, json={**CFG, "usar_ia": False})
    assert cliente.post("/perguntar", headers=ANA, json={"pergunta": "cachorra Mel"}).json()["gerada_por_ia"] is False


def test_config_invalida_e_recusada(cliente):
    assert cliente.put("/config", headers=ANA, json={**CFG, "chunk_overlap": 500}).status_code == 400
    assert cliente.put("/config", headers=ANA, json={**CFG, "chunk_size": 50}).status_code == 422
    assert cliente.put("/config", headers=ANA, json={**CFG, "modelo_llm": "gpt-9"}).status_code == 400


def test_previa_chunking_nao_salva_nada(cliente):
    texto = "Primeiro parágrafo sobre a infância.\n\n" * 20
    r = cliente.post("/lab/chunking", json={"texto": texto, "chunk_size": 200, "chunk_overlap": 0}).json()
    assert r["total"] > 1 and max(r["tamanhos"]) <= 200
    assert BANCO["memorias"] == []


def test_reprocessar_refaz_chunks_com_nova_config(cliente):
    texto = "Frase sobre a minha vida pessoal e meus planos. " * 40  # ~1900 caracteres
    mid = cliente.post("/memorias", headers=ANA, json={"texto": texto}).json()["id"]
    antes = len(cliente.get(f"/memorias/{mid}/chunks", headers=ANA).json())
    cliente.put("/config", headers=ANA, json={**CFG, "chunk_size": 300, "chunk_overlap": 50})
    r = cliente.post("/memorias/reprocessar", headers=ANA).json()
    depois = len(cliente.get(f"/memorias/{mid}/chunks", headers=ANA).json())
    assert r["memorias"] == 1 and depois > antes
    assert cliente.get(f"/memorias/{mid}/chunks", headers=BETO).json() == []


CONVERSA = """03/11/2026 09:01 - João: Bora viajar em dezembro?
03/11/2026 09:02 - Bruno: Bora! Pensei em Floripa
04/11/2026 20:15 - Bruno: Reservei a pousada: 650 reais por 3 noites"""


def test_importar_whatsapp_previa_nao_salva(cliente):
    r = cliente.post("/importar/whatsapp", headers=ANA, json={"conteudo": CONVERSA, "nome_conversa": "João"}).json()
    assert r["salvo"] is False and r["mensagens"] == 3 and r["blocos"] == 2
    assert r["participantes"] == ["Bruno", "João"] and BANCO["memorias"] == []


def test_importar_whatsapp_salva_e_busca(cliente):
    r = cliente.post("/importar/whatsapp", headers=ANA, json={
        "conteudo": CONVERSA, "nome_conversa": "João", "categoria": "viagens", "confirmar": True}).json()
    assert r["salvo"] is True and r["memorias_criadas"] == 2
    f = cliente.post("/buscar", headers=ANA, json={"pergunta": "pousada reais noites"}).json()
    assert "650 reais" in f[0]["texto"] and f[0]["categoria"] == "viagens" and f[0]["data"] == "04/11/2026"
    assert cliente.get("/memorias", headers=BETO).json() == []


def test_importar_arquivo_invalido(cliente):
    r = cliente.post("/importar/whatsapp", headers=ANA, json={"conteudo": "isto não é uma conversa", "nome_conversa": "x"})
    assert r.status_code == 400 and "Exportar conversa" in r.json()["detail"]


class LLMComJson(LLMFalso):
    def __init__(self, categoria, e_nova):
        self.c, self.n = categoria, e_nova

    def gerar_json(self, system, prompt, esquema):
        LLMComJson.prompt = prompt
        return esquema(categoria=self.c, e_nova=self.n, motivo="teste")


def test_sugerir_categoria_existente(cliente, monkeypatch):
    cliente.post("/categorias", headers=ANA, json={"nome": "finanças"})
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMComJson("Finanças ", False))
    r = cliente.post("/categorias/sugerir", headers=ANA, json={"texto": "Paguei 300 reais de luz este mês."}).json()
    assert r == {"categoria": "finanças", "nova": False, "motivo": "teste"}
    assert "finanças" in LLMComJson.prompt, "o LLM recebe as categorias do usuário"


def test_sugerir_categoria_nova_e_validacao(cliente, monkeypatch):
    # o LLM diz que é existente, mas inventa um nome que não está na lista: o código corrige para "nova"
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMComJson("Pets", False))
    r = cliente.post("/categorias/sugerir", headers=ANA, json={"texto": "A Mel foi ao veterinário hoje."}).json()
    assert r["categoria"] == "pets" and r["nova"] is True


def test_sem_ia_nao_sugere(cliente, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda _: None)
    assert cliente.post("/categorias/sugerir", headers=ANA, json={"texto": "Texto longo o bastante aqui."}).json() == {}


import base64


class LLMTranscritor(LLMFalso):
    def transcrever(self, audio, mime):
        LLMTranscritor.recebido = (audio, mime)
        return "Hoje paguei R$ 320 no mercado."


def test_transcrever_audio(cliente, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMTranscritor())
    b64 = base64.b64encode(b"audio-falso").decode()
    r = cliente.post("/audio/transcrever", headers=ANA, json={"audio_b64": b64, "mime": "audio/webm;codecs=opus"})
    assert r.status_code == 200 and r.json()["texto"] == "Hoje paguei R$ 320 no mercado."
    assert LLMTranscritor.recebido == (b"audio-falso", "audio/webm"), "o parâmetro ';codecs' é removido"


def test_transcrever_recusa_formato_e_base64_invalidos(cliente, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMTranscritor())
    b64 = base64.b64encode(b"x" * 20).decode()
    assert cliente.post("/audio/transcrever", headers=ANA, json={"audio_b64": b64, "mime": "video/mp4"}).status_code == 400
    assert cliente.post("/audio/transcrever", headers=ANA, json={"audio_b64": "não é base64!!", "mime": "audio/webm"}).status_code == 400


def test_transcrever_respeita_ia_desligada(cliente, monkeypatch):
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMTranscritor())
    cliente.put("/config", headers=ANA, json={**CFG, "usar_ia": False})
    r = cliente.post("/audio/transcrever", headers=ANA, json={"audio_b64": base64.b64encode(b"x" * 20).decode(), "mime": "audio/webm"})
    assert r.status_code == 400 and "Usar IA" in r.json()["detail"]



class LLMPerfil(LLMFalso):
    chamadas = 0

    def gerar(self, system, prompt):
        if "PERFIL" in system:
            LLMPerfil.chamadas += 1
            LLMPerfil.entrada = prompt
            return "- chama dinheiro de grana\n- prefere respostas curtas"
        return super().gerar(system, prompt)


def test_feedback_reaprende_perfil_a_cada_5(cliente, monkeypatch):
    LLMPerfil.chamadas = 0
    monkeypatch.setattr(rag, "get_llm", lambda _: LLMPerfil())
    cliente.post("/memorias", headers=ANA, json={"texto": "Gastei muita grana no mercado."})
    for i in range(4):
        r = cliente.post("/feedback", headers=ANA, json={"pergunta": f"p{i}", "resposta": "r", "util": i % 2 == 0})
        assert r.json() == {"salvo": True, "perfil_atualizado": False}
    r = cliente.post("/feedback", headers=ANA, json={"pergunta": "p4", "resposta": "longa demais", "util": False,
                                                    "comentario": "seja mais curto"}).json()
    assert r["perfil_atualizado"] is True and LLMPerfil.chamadas == 1
    assert "seja mais curto" in LLMPerfil.entrada and "grana" in LLMPerfil.entrada
    assert "grana" in cliente.get("/config", headers=ANA).json()["perfil_estilo"]
    # o perfil entra nas instruções DEPOIS das regras
    cliente.post("/perguntar", headers=ANA, json={"pergunta": "mercado"})
    assert LLMFalso.ultimo_system.index("Regras") < LLMFalso.ultimo_system.index("chama dinheiro de grana")
    # e conta de novo a partir daí
    r = cliente.post("/feedback", headers=ANA, json={"pergunta": "p5", "resposta": "r", "util": True}).json()
    assert r["perfil_atualizado"] is False


def test_perfil_editavel_e_isolado(cliente):
    cliente.put("/config", headers=ANA, json={**CFG, "perfil_estilo": "- me chama de chefe"})
    assert cliente.get("/config", headers=ANA).json()["perfil_estilo"] == "- me chama de chefe"
    assert cliente.get("/config", headers=BETO).json()["perfil_estilo"] == ""

"""Testes do bot do WhatsApp (sem internet: banco e Meta falsos)."""

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from lembra import api, rag, whatsapp_bot
from lembra.rag import Resposta
from lembra.supabase import ErroSupabase, Trecho
from lembra.whatsapp_bot import (
    MensagemRecebida,
    assinatura_valida,
    classificar,
    emitir_jwt,
    extrair_mensagens,
    processar_webhook,
    responder,
)

SEGREDO = "segredo-do-app"


def _assinar(corpo: bytes, segredo: str = SEGREDO) -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


# ------------------------------------------------------------- segurança
def test_assinatura_confere_so_o_corpo_exato():
    corpo = b'{"entry":[]}'
    assert assinatura_valida(corpo, _assinar(corpo), SEGREDO)
    assert not assinatura_valida(corpo + b" ", _assinar(corpo), SEGREDO), "1 byte a mais invalida"
    assert not assinatura_valida(corpo, _assinar(corpo, "outro"), SEGREDO), "segredo errado"
    assert not assinatura_valida(corpo, None, SEGREDO), "sem cabeçalho"
    assert not assinatura_valida(corpo, _assinar(corpo), ""), "servidor sem segredo nunca aceita"


def _decodificar(parte: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(parte + "=" * (-len(parte) % 4)))


def test_jwt_emitido_tem_assinatura_e_dados_corretos():
    token = emitir_jwt("s3gr3d0", "authenticated", sub="uuid-da-ana", validade=300)
    cab, conteudo, assinatura = token.split(".")
    assert _decodificar(cab) == {"alg": "HS256", "typ": "JWT"}
    dados = _decodificar(conteudo)
    assert dados["sub"] == "uuid-da-ana" and dados["role"] == "authenticated"
    assert 290 <= dados["exp"] - int(time.time()) <= 300, "vida curta"
    esperado = base64.urlsafe_b64encode(
        hmac.new(b"s3gr3d0", f"{cab}.{conteudo}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    assert assinatura == esperado
    assert "sub" not in _decodificar(emitir_jwt("s", "service_role").split(".")[1])


# ------------------------------------------------------------- interpretação
@pytest.mark.parametrize(("texto", "esperado"), [
    ("VINCULAR abcd2345", ("vincular", "ABCD2345")),
    ("  vincular ABCD2345 ", ("vincular", "ABCD2345")),
    ("Quando é o dentista?", ("pergunta", "Quando é o dentista?")),
    ("? dentista", ("pergunta", "dentista")),
    ("Ajuda", ("ajuda", "")),
    ("oi!", ("ajuda", "")),
    ("Paguei 300 de luz", ("memoria", "Paguei 300 de luz")),
    ("vincular meu cartão ao app", ("memoria", "vincular meu cartão ao app")),
])
def test_classificar(texto, esperado):
    assert classificar(texto) == esperado


def test_extrair_ignora_status_e_le_texto_e_audio():
    payload = {"entry": [{"changes": [{"value": {
        "statuses": [{"id": "x", "status": "read"}],
        "messages": [
            {"id": "m1", "from": "5511999990000", "type": "text", "text": {"body": "oi"}},
            {"id": "m2", "from": "5511999990000", "type": "audio",
             "audio": {"id": "midia9", "mime_type": "audio/ogg; codecs=opus"}},
        ]}}]}]}
    msgs = extrair_mensagens(payload)
    assert [(m.id, m.tipo) for m in msgs] == [("m1", "text"), ("m2", "audio")]
    assert msgs[0].texto == "oi" and msgs[1].midia_id == "midia9"
    assert extrair_mensagens({"entry": [{"changes": [{"value": {"statuses": []}}]}]}) == []


# ------------------------------------------------------------- orquestração
class RepoFalso:
    def __init__(self):
        self.memorias, self.categorias = [], []

    def criar_categoria(self, nome):
        self.categorias.append(nome)


class BancoFalso:
    def __init__(self, vinculos=None, codigos=None):
        self.vistas, self.vinculos, self.codigos = set(), dict(vinculos or {}), dict(codigos or {})
        self.repos = {}

    def primeira_vez(self, mid):
        nova = mid not in self.vistas
        self.vistas.add(mid)
        return nova

    def dono(self, tel):
        return self.vinculos.get(tel)

    def vincular(self, codigo, tel):
        if codigo == "BLOQUEADO":
            raise ErroSupabase(400, "muitas tentativas; aguarde uma hora")
        dono = self.codigos.pop(codigo, None)
        if dono:
            self.vinculos[tel] = dono
        return dono

    def repositorio_de(self, uid):
        return self.repos.setdefault(uid, RepoFalso())


class MetaFalsa:
    def __init__(self):
        self.enviadas = []

    def enviar(self, tel, texto):
        self.enviadas.append((tel, texto))

    def baixar_midia(self, midia_id):
        return b"bytes-de-audio"


ANA = "5511999990000"


def _texto(t, mid="m1", tel=ANA):
    return MensagemRecebida(id=mid, telefone=tel, tipo="text", texto=t)


@pytest.fixture
def rag_falso(monkeypatch):
    chamadas = {}
    monkeypatch.setattr(rag, "perguntar", lambda repo, p: Resposta(
        f"Resposta para: {p}", [Trecho("t", {"data": "2026-11-03"}, 0.9)], True))
    monkeypatch.setattr(rag, "sugerir_categoria",
                        lambda repo, t: {"categoria": "saúde", "nova": True, "motivo": ""})

    def alimentar(repo, texto, categoria):
        repo.memorias.append((texto, categoria))
        return "id", 1

    monkeypatch.setattr(rag, "alimentar", alimentar)
    monkeypatch.setattr(rag, "transcrever_audio", lambda repo, audio, mime: "Quando é o dentista?")
    return chamadas


def test_numero_nao_vinculado_recebe_instrucoes(rag_falso):
    assert "VINCULAR" in responder(_texto("oi"), BancoFalso(), MetaFalsa())


def test_vincular_com_codigo_valido_invalido_e_bloqueado(rag_falso):
    banco = BancoFalso(codigos={"ABCD2345": "uid-ana"})
    assert responder(_texto("VINCULAR abcd2345"), banco, MetaFalsa()).startswith("✅")
    assert banco.dono(ANA) == "uid-ana"
    assert "inválido" in responder(_texto("VINCULAR ABCD2345", mid="m2"), banco, MetaFalsa()), "uso único"
    assert "aguarde" in responder(_texto("VINCULAR BLOQUEADO", mid="m3"), banco, MetaFalsa())


def test_mensagem_repetida_pela_meta_e_ignorada(rag_falso):
    banco = BancoFalso(vinculos={ANA: "uid-ana"})
    assert responder(_texto("Paguei 300 de luz"), banco, MetaFalsa())
    assert responder(_texto("Paguei 300 de luz"), banco, MetaFalsa()) is None
    assert len(banco.repositorio_de("uid-ana").memorias) == 1, "não salva duas vezes"


def test_texto_vira_memoria_na_categoria_sugerida(rag_falso):
    banco = BancoFalso(vinculos={ANA: "uid-ana"})
    assert responder(_texto("Dentista dia 20 às 14h"), banco, MetaFalsa()) == "✅ Guardei em *saúde*."
    repo = banco.repositorio_de("uid-ana")
    assert repo.memorias == [("Dentista dia 20 às 14h", "saúde")] and repo.categorias == ["saúde"]


def test_pergunta_responde_com_fontes(rag_falso):
    r = responder(_texto("Quando é o dentista?"), BancoFalso(vinculos={ANA: "uid-ana"}), MetaFalsa())
    assert r.startswith("Resposta para: Quando é o dentista?") and "1 memória(s)" in r


def test_audio_e_transcrito_e_vira_pergunta(rag_falso):
    msg = MensagemRecebida(id="a1", telefone=ANA, tipo="audio", midia_id="m", mime="audio/ogg")
    r = responder(msg, BancoFalso(vinculos={ANA: "uid-ana"}), MetaFalsa())
    assert r.startswith("🎙️ _Quando é o dentista?_") and "Resposta para" in r


def test_cada_numero_so_alcanca_a_propria_conta(rag_falso):
    banco = BancoFalso(vinculos={ANA: "uid-ana", "5521888880000": "uid-bia"})
    responder(_texto("segredo da Bia", tel="5521888880000"), banco, MetaFalsa())
    assert banco.repositorio_de("uid-ana").memorias == []
    assert banco.repositorio_de("uid-bia").memorias == [("segredo da Bia", "saúde")]


def test_erro_numa_mensagem_nao_deixa_pessoa_sem_resposta(monkeypatch, rag_falso):
    monkeypatch.setattr(rag, "alimentar", lambda *a: (_ for _ in ()).throw(RuntimeError("caiu")))
    meta = MetaFalsa()
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "m1", "from": ANA, "type": "text", "text": {"body": "Paguei a luz"}}]}}]}]}
    assert processar_webhook(payload, BancoFalso(vinculos={ANA: "uid-ana"}), meta) == 1
    assert "problema" in meta.enviadas[0][1]


# ------------------------------------------------------------- endpoints
@pytest.fixture
def cliente_whatsapp(monkeypatch):
    for k, v in {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_ID": "p", "WHATSAPP_APP_SECRET": SEGREDO,
                 "WHATSAPP_VERIFY_TOKEN": "combinado", "SUPABASE_JWT_SECRET": "j"}.items():
        monkeypatch.setenv(k, v)
    return TestClient(api.app)


def test_verificacao_do_webhook(cliente_whatsapp):
    ok = cliente_whatsapp.get("/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "combinado", "hub.challenge": "123"})
    assert ok.status_code == 200 and ok.text == "123"
    errado = cliente_whatsapp.get("/whatsapp/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "chute", "hub.challenge": "123"})
    assert errado.status_code == 403


def test_webhook_recusa_assinatura_falsa_e_aceita_a_verdadeira(cliente_whatsapp, monkeypatch):
    recebidos = []
    monkeypatch.setattr(whatsapp_bot, "processar_webhook", lambda p, b, m: recebidos.append(p) or 0)
    corpo = b'{"entry":[]}'
    falso = cliente_whatsapp.post("/whatsapp/webhook", content=corpo,
                                  headers={"X-Hub-Signature-256": _assinar(corpo, "chute")})
    assert falso.status_code == 401 and recebidos == []
    ok = cliente_whatsapp.post("/whatsapp/webhook", content=corpo,
                               headers={"X-Hub-Signature-256": _assinar(corpo)})
    assert ok.status_code == 200 and recebidos == [{"entry": []}]


def test_webhook_sem_configuracao_responde_503(monkeypatch):
    monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
    r = TestClient(api.app).post("/whatsapp/webhook", content=b"{}")
    assert r.status_code == 503


@pytest.mark.parametrize(("veio", "envia"), [
    ("553188887777", "5531988887777"),   # celular BR sem o 9 -> ganha o 9 depois do DDD
    ("5531988887777", "5531988887777"),  # já completo: intacto
    ("553133334444", "553133334444"),    # fixo (começa com 3): intacto
    ("15551568101", "15551568101"),      # outro país: intacto
])
def test_numero_para_envio_corrige_o_nono_digito(veio, envia):
    assert whatsapp_bot.numero_para_envio(veio) == envia

"""Banco fora do ar (projeto pausado, rede): o usuário vê um aviso legível, nunca uma página HTML."""

import pytest
import requests
from fastapi import Depends
from fastapi.testclient import TestClient

from lembra import api
from lembra.supabase import MSG_BANCO_FORA, ErroSupabase, _checar, _http

PAGINA_CLOUDFLARE = "<!DOCTYPE html><html><head><title>supabase.co | 521: Web server is down</title></head>" + "x" * 3000


def _resposta(status: int, corpo: str, tipo: str) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = corpo.encode()
    r.headers["Content-Type"] = tipo
    return r


def test_pagina_html_do_cloudflare_vira_mensagem_legivel():
    with pytest.raises(ErroSupabase) as e:
        _checar(_resposta(521, PAGINA_CLOUDFLARE, "text/html"))
    assert e.value.status == 521 and e.value.mensagem == MSG_BANCO_FORA
    assert "<html" not in e.value.mensagem


def test_erro_json_do_supabase_continua_com_a_mensagem_dele():
    with pytest.raises(ErroSupabase) as e:
        _checar(_resposta(400, '{"msg": "Invalid login credentials"}', "application/json"))
    assert e.value.mensagem == "Invalid login credentials"


def test_falha_de_conexao_vira_erro_503_legivel(monkeypatch):
    def sem_rede(self, *a, **k):
        raise requests.ConnectionError("Name or service not known")

    monkeypatch.setattr(requests.Session, "request", sem_rede)
    with pytest.raises(ErroSupabase) as e:
        _http.get("https://exemplo.supabase.co/rest/v1/memorias")
    assert e.value.status == 503 and e.value.mensagem == MSG_BANCO_FORA


def test_api_responde_503_com_aviso_quando_o_banco_esta_fora():
    class RepoForaDoAr:
        def listar_categorias(self):
            raise ErroSupabase(521, MSG_BANCO_FORA)

    api.app.dependency_overrides[api.repositorio] = lambda cred=Depends(api._bearer): RepoForaDoAr()
    try:
        r = TestClient(api.app).get("/categorias", headers={"Authorization": "Bearer x"})
    finally:
        api.app.dependency_overrides.clear()
    assert r.status_code == 503 and r.json()["detail"] == MSG_BANCO_FORA


def test_ping_do_banco_ok_e_banco_fora(monkeypatch):
    monkeypatch.delenv("CRON_SECRET", raising=False)  # o teste não pode depender do ambiente da máquina
    chamadas = []

    def get(url, **kw):
        chamadas.append(url)
        return _resposta(200, "[]", "application/json")

    monkeypatch.setattr(_http, "get", get)
    c = TestClient(api.app)
    assert c.get("/saude/banco").json() == {"banco": "ok"}
    assert chamadas and chamadas[0].endswith("/rest/v1/memorias")

    monkeypatch.setattr(_http, "get", lambda url, **kw: _resposta(521, PAGINA_CLOUDFLARE, "text/html"))
    r = c.get("/saude/banco")
    assert r.status_code == 503 and r.json()["detail"] == MSG_BANCO_FORA


def test_ping_exige_o_segredo_do_cron_quando_configurado(monkeypatch):
    monkeypatch.setattr(_http, "get", lambda url, **kw: _resposta(200, "[]", "application/json"))
    c = TestClient(api.app)
    monkeypatch.setenv("CRON_SECRET", "segredo-do-cron")
    assert c.get("/saude/banco").status_code == 401, "sem cabeçalho"
    assert c.get("/saude/banco", headers={"Authorization": "Bearer errado"}).status_code == 401
    ok = c.get("/saude/banco", headers={"Authorization": "Bearer segredo-do-cron"})
    assert ok.status_code == 200 and ok.json() == {"banco": "ok"}
    monkeypatch.delenv("CRON_SECRET")
    assert c.get("/saude/banco").status_code == 200, "sem segredo configurado, continua aberto"

"""Conversa com o Supabase: login (Auth) e dados (PostgREST), sempre com o crachá do usuário.

Por que não usar a chave administrativa (service_role)? Porque ela IGNORA o Row Level
Security. Usando o crachá (JWT) de quem está logado, o próprio banco garante que cada
pessoa só lê e grava os próprios dados, mesmo se houver bug neste código.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

TIMEOUT = 30


class ErroSupabase(Exception):
    def __init__(self, status: int, mensagem: str):
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


@dataclass
class Trecho:
    """Um chunk recuperado pela busca."""

    texto: str
    metadados: dict
    similaridade: float


def _vetor_para_texto(vetor: list[float]) -> str:
    # pgvector aceita vetores no formato texto "[0.1,0.2,...]"
    return "[" + ",".join(f"{x:.7f}" for x in vetor) + "]"


def _checar(r: requests.Response):
    if r.ok:
        return r.json() if r.content else None
    try:
        corpo = r.json()
        msg = corpo.get("msg") or corpo.get("message") or corpo.get("error_description") or str(corpo)
    except ValueError:
        msg = r.text
    raise ErroSupabase(r.status_code, msg)


class SupabaseAuth:
    """Cadastro e login. Usa só a chave pública (publishable)."""

    def __init__(self, url: str, chave_publica: str):
        self.url = url.rstrip("/")
        self.headers = {"apikey": chave_publica, "Content-Type": "application/json"}

    def cadastrar(self, email: str, senha: str, convite: str) -> dict:
        # O código de convite vai nos metadados; o trigger do banco valida e pode recusar.
        r = requests.post(
            f"{self.url}/auth/v1/signup",
            headers=self.headers,
            json={"email": email, "password": senha, "data": {"convite": convite}},
            timeout=TIMEOUT,
        )
        return _sessao(_checar(r))

    def entrar(self, email: str, senha: str) -> dict:
        r = requests.post(
            f"{self.url}/auth/v1/token?grant_type=password",
            headers=self.headers,
            json={"email": email, "password": senha},
            timeout=TIMEOUT,
        )
        return _sessao(_checar(r))

    def renovar(self, refresh_token: str) -> dict:
        """Troca o refresh token por um crachá novo, sem pedir a senha de novo."""
        r = requests.post(
            f"{self.url}/auth/v1/token?grant_type=refresh_token",
            headers=self.headers,
            json={"refresh_token": refresh_token},
            timeout=TIMEOUT,
        )
        return _sessao(_checar(r))


def _sessao(d: dict) -> dict:
    return {
        "access_token": d["access_token"],
        "refresh_token": d["refresh_token"],
        "expira_em_segundos": d.get("expires_in"),
        "usuario": {"id": d["user"]["id"], "email": d["user"]["email"]},
    }


class RepositorioSupabase:
    """Memórias e chunks de UM usuário (o dono do crachá)."""

    def __init__(self, url: str, chave_publica: str, access_token: str):
        self.url = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": chave_publica,
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    def salvar_memoria(
        self, texto: str, categoria: str, data_evento: str, chunks: list[str],
        vetores: list[list[float]], modelo: str,
    ) -> str:
        payload = {
            "p_modelo": modelo,
            "p_texto": texto,
            "p_categoria": categoria,
            "p_data_evento": data_evento,
            "p_chunks": [
                {"indice": i, "texto": t, "embedding": _vetor_para_texto(v)}
                for i, (t, v) in enumerate(zip(chunks, vetores))
            ],
        }
        r = requests.post(f"{self.url}/rpc/salvar_memoria", headers=self.headers, json=payload, timeout=TIMEOUT)
        return _checar(r)

    def listar_memorias(self, categoria: str | None = None, limite: int = 50) -> list[dict]:
        params = {
            "select": "id,texto,categoria,data_evento,criado_em",
            "order": "criado_em.desc",
            "limit": str(limite),
        }
        if categoria:
            params["categoria"] = f"eq.{categoria}"
        r = requests.get(f"{self.url}/memorias", headers=self.headers, params=params, timeout=TIMEOUT)
        return _checar(r)

    def apagar_memoria(self, memoria_id: str) -> bool:
        h = {**self.headers, "Prefer": "return=representation"}
        r = requests.delete(f"{self.url}/memorias", headers=h, params={"id": f"eq.{memoria_id}"}, timeout=TIMEOUT)
        return len(_checar(r) or []) > 0

    def buscar(
        self, vetor: list[float], k: int, categoria: str | None = None, modelo: str | None = None
    ) -> list[Trecho]:
        payload = {"query_embedding": _vetor_para_texto(vetor), "k": k, "filtro_categoria": categoria}
        if modelo:
            payload["modelo"] = modelo
        r = requests.post(f"{self.url}/rpc/buscar_chunks", headers=self.headers, json=payload, timeout=TIMEOUT)
        return [
            Trecho(
                texto=l["texto"],
                metadados={"memoria_id": l["memoria_id"], "categoria": l["categoria"], "data": l["data_evento"]},
                similaridade=l["similaridade"],
            )
            for l in _checar(r)
        ]

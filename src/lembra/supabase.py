"""Conversa com o Supabase: login (Auth) e dados (PostgREST), sempre com o crachá do usuário.

Por que não usar a chave administrativa (service_role)? Porque ela IGNORA o Row Level
Security. Usando o crachá (JWT) de quem está logado, o próprio banco garante que cada
pessoa só lê e grava os próprios dados, mesmo se houver bug neste código.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

TIMEOUT = 30

# UMA sessão HTTP reaproveitada (keep-alive): a conexão segura (TLS) é aberta uma vez e reusada.
# Sem isso, cada consulta refazia o "aperto de mão" de criptografia (várias idas e voltas pela rede).
_http = requests.Session()
_http.mount("https://", requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16))


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

    def cadastrar(self, email: str, senha: str) -> dict:
        # Cadastro livre: qualquer pessoa cria a própria conta (sem convite).
        r = _http.post(
            f"{self.url}/auth/v1/signup",
            headers=self.headers,
            json={"email": email, "password": senha},
            timeout=TIMEOUT,
        )
        return _sessao(_checar(r))

    def entrar(self, email: str, senha: str) -> dict:
        r = _http.post(
            f"{self.url}/auth/v1/token?grant_type=password",
            headers=self.headers,
            json={"email": email, "password": senha},
            timeout=TIMEOUT,
        )
        return _sessao(_checar(r))

    def email_de(self, access_token: str) -> str:
        """E-mail do dono do crachá (o Supabase confirma o crachá e devolve o usuário)."""
        r = _http.get(f"{self.url}/auth/v1/user", headers={**self.headers, "Authorization": f"Bearer {access_token}"},
                      timeout=TIMEOUT)
        return _checar(r)["email"]

    def renovar(self, refresh_token: str) -> dict:
        """Troca o refresh token por um crachá novo, sem pedir a senha de novo."""
        r = _http.post(
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
        r = _http.post(f"{self.url}/rpc/salvar_memoria", headers=self.headers, json=payload, timeout=TIMEOUT)
        return _checar(r)

    def listar_memorias(self, categoria: str | None = None, limite: int = 200) -> list[dict]:
        params = {
            "select": "id,texto,categoria,data_evento,criado_em",
            "order": "criado_em.desc",
            "limit": str(limite),
        }
        if categoria:
            params["categoria"] = f"eq.{categoria}"
        r = _http.get(f"{self.url}/memorias", headers=self.headers, params=params, timeout=TIMEOUT)
        return _checar(r)

    def obter_memoria(self, memoria_id: str) -> dict | None:
        params = {"select": "id,texto,categoria,data_evento,criado_em", "id": f"eq.{memoria_id}"}
        r = _http.get(f"{self.url}/memorias", headers=self.headers, params=params, timeout=TIMEOUT)
        linhas = _checar(r)
        return linhas[0] if linhas else None

    def atualizar_memoria(
        self, memoria_id: str, texto: str, categoria: str, data_evento: str,
        chunks: list[str] | None = None, vetores: list[list[float]] | None = None, modelo: str | None = None,
    ) -> bool:
        payload = {"p_id": memoria_id, "p_texto": texto, "p_categoria": categoria,
                   "p_data_evento": data_evento, "p_chunks": None}
        if chunks is not None:
            payload["p_chunks"] = [
                {"indice": i, "texto": t, "embedding": _vetor_para_texto(v)}
                for i, (t, v) in enumerate(zip(chunks, vetores))
            ]
            payload["p_modelo"] = modelo
        r = _http.post(f"{self.url}/rpc/atualizar_memoria", headers=self.headers, json=payload, timeout=TIMEOUT)
        return bool(_checar(r))

    def listar_chunks(self, memoria_id: str) -> list[dict]:
        params = {"select": "indice,texto,modelo_embedding", "memoria_id": f"eq.{memoria_id}", "order": "indice"}
        r = _http.get(f"{self.url}/chunks", headers=self.headers, params=params, timeout=TIMEOUT)
        return _checar(r)

    # ---------- Configuração do RAG ----------

    def obter_config(self) -> dict | None:
        r = _http.get(f"{self.url}/config_rag", headers=self.headers, params={"select": "*"}, timeout=TIMEOUT)
        linhas = _checar(r)
        return linhas[0] if linhas else None

    def salvar_config(self, cfg: dict) -> dict:
        # "upsert": cria a linha se não existir, atualiza se existir
        h = {**self.headers, "Prefer": "resolution=merge-duplicates,return=representation"}
        r = _http.post(f"{self.url}/config_rag", headers=h, params={"on_conflict": "user_id"},
                          json={**cfg, "atualizado_em": "now()"}, timeout=TIMEOUT)
        return _checar(r)[0]

    # ---------- Feedback e perfil ----------

    def registrar_feedback(self, pergunta: str, resposta: str, util: bool, comentario: str | None) -> None:
        r = _http.post(f"{self.url}/feedback", headers=self.headers, timeout=TIMEOUT,
                       json={"pergunta": pergunta[:2000], "resposta": resposta[:6000], "util": util,
                             "comentario": (comentario or None) and comentario[:500]})
        _checar(r)

    def listar_feedback(self, limite: int = 20, desde: str | None = None) -> list[dict]:
        params = {"select": "pergunta,resposta,util,comentario,criado_em", "order": "criado_em.desc",
                  "limit": str(limite)}
        if desde:
            params["criado_em"] = f"gt.{desde}"
        r = _http.get(f"{self.url}/feedback", headers=self.headers, params=params, timeout=TIMEOUT)
        return _checar(r)

    def salvar_perfil(self, perfil: str) -> None:
        h = {**self.headers, "Prefer": "resolution=merge-duplicates"}
        r = _http.post(f"{self.url}/config_rag", headers=h, params={"on_conflict": "user_id"}, timeout=TIMEOUT,
                       json={"perfil_estilo": perfil[:800], "perfil_atualizado_em": "now()"})
        _checar(r)

    # ---------- Categorias ----------

    def listar_categorias(self) -> list[dict]:
        r = _http.post(f"{self.url}/rpc/listar_categorias", headers=self.headers, json={}, timeout=TIMEOUT)
        return _checar(r)

    def criar_categoria(self, nome: str) -> None:
        h = {**self.headers, "Prefer": "resolution=ignore-duplicates"}
        r = _http.post(f"{self.url}/categorias", headers=h, json={"nome": nome.strip().lower()}, timeout=TIMEOUT)
        _checar(r)

    def renomear_categoria(self, antigo: str, novo: str) -> None:
        r = _http.post(f"{self.url}/rpc/renomear_categoria", headers=self.headers,
                          json={"p_antigo": antigo, "p_novo": novo}, timeout=TIMEOUT)
        _checar(r)

    def apagar_categoria(self, nome: str, mover_para: str = "geral") -> int:
        r = _http.post(f"{self.url}/rpc/apagar_categoria", headers=self.headers,
                          json={"p_nome": nome, "p_mover_para": mover_para}, timeout=TIMEOUT)
        return _checar(r) or 0

    def gerar_codigo_whatsapp(self) -> str:
        r = _http.post(f"{self.url}/rpc/whatsapp_gerar_codigo", headers=self.headers, json={}, timeout=TIMEOUT)
        return _checar(r)

    def vinculo_whatsapp(self) -> dict | None:
        r = _http.get(f"{self.url}/whatsapp_vinculos", headers=self.headers,
                      params={"select": "telefone,criado_em"}, timeout=TIMEOUT)
        linhas = _checar(r) or []
        return linhas[0] if linhas else None

    def desvincular_whatsapp(self) -> None:
        # Sem filtro explícito: o RLS ("dono apaga seu vinculo") já limita ao próprio usuário.
        r = _http.delete(f"{self.url}/whatsapp_vinculos", headers=self.headers,
                         params={"telefone": "not.is.null"}, timeout=TIMEOUT)
        _checar(r)

    def exportar_tudo(self) -> dict:
        """Portabilidade (LGPD art. 18, V): tudo o que é DESTA pessoa, em formato aberto. Os chunks e
        vetores ficam de fora: são derivados do texto e podem ser recalculados."""
        config = self.obter_config() or {}
        return {
            "memorias": self.listar_memorias(limite=100_000),
            "categorias": self.listar_categorias(),
            "configuracoes": {k: v for k, v in config.items() if k != "user_id"},
            "avaliacoes": self.listar_feedback(limite=100_000),
            "whatsapp": self.vinculo_whatsapp(),
        }

    def apagar_conta(self) -> None:
        """Apaga a conta de quem está logado e, em cascata, todos os dados dela (ver a migration)."""
        r = _http.post(f"{self.url}/rpc/apagar_minha_conta", headers=self.headers, json={}, timeout=TIMEOUT)
        _checar(r)

    def apagar_memoria(self, memoria_id: str) -> bool:
        h = {**self.headers, "Prefer": "return=representation"}
        r = _http.delete(f"{self.url}/memorias", headers=h, params={"id": f"eq.{memoria_id}"}, timeout=TIMEOUT)
        return len(_checar(r) or []) > 0

    def buscar(
        self, vetor: list[float], k: int, categoria: str | None = None, modelo: str | None = None
    ) -> list[Trecho]:
        payload = {"query_embedding": _vetor_para_texto(vetor), "k": k, "filtro_categoria": categoria}
        if modelo:
            payload["modelo"] = modelo
        r = _http.post(f"{self.url}/rpc/buscar_chunks", headers=self.headers, json=payload, timeout=TIMEOUT)
        return [
            Trecho(
                texto=l["texto"],
                metadados={"memoria_id": l["memoria_id"], "categoria": l["categoria"], "data": l["data_evento"]},
                similaridade=l["similaridade"],
            )
            for l in _checar(r)
        ]

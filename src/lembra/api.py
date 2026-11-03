"""API do Lembra: os "endereços" que o app do celular chama.

Rodar:   uvicorn lembra.api:app --reload
Testar:  abra http://localhost:8000/docs (página interativa gerada automaticamente)

Toda rota de dados exige o cabeçalho  Authorization: Bearer <access_token>.
A API repassa esse crachá ao Supabase; quem decide o que a pessoa pode ver é o banco (RLS).
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from . import rag
from .config import get_settings
from .supabase import ErroSupabase, RepositorioSupabase, SupabaseAuth

logger = logging.getLogger("lembra")


@asynccontextmanager
async def _ciclo_de_vida(_app):
    # "Aquecimento": carrega o modelo de embeddings ao ligar o servidor, para que a primeira
    # pessoa a usar o app não espere esse carregamento (alguns segundos).
    if os.getenv("LEMBRA_AQUECER", "1") == "1":
        try:
            from .config import embedder_de

            s = get_settings()
            if s.embedding_provider == "local":  # só o modelo local precisa ser carregado
                embedder_de(s).embed_query("aquecimento")
                logger.info("Modelo de embeddings carregado")
        except Exception as e:  # sem o modelo o app ainda abre; o erro aparece no primeiro uso
            logger.warning("Não consegui pré-carregar o modelo: %s", e)
    yield


app = FastAPI(title="Lembra API", version="0.2.0", description="Assistente de vida pessoal com RAG.",
              lifespan=_ciclo_de_vida)
_bearer = HTTPBearer(description="access_token recebido no login")

# CORS: quando o app for hospedado em outro endereço (ex.: Vercel), o navegador só deixa ele
# chamar esta API se o endereço estiver nesta lista. Ex.: ALLOWED_ORIGINS=https://lembra.vercel.app
_origens = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origens:
    app.add_middleware(CORSMiddleware, allow_origins=_origens, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type"])


# ---------- Modelos (formato dos dados que entram e saem) ----------

class Cadastro(BaseModel):
    email: EmailStr
    senha: str = Field(min_length=8)
    convite: str | None = None  # opcional: só usado se a trava de convites for religada


class Login(BaseModel):
    email: EmailStr
    senha: str


class Renovar(BaseModel):
    refresh_token: str


class NovaMemoria(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    categoria: str = "geral"
    data_evento: str = ""


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2_000)
    categoria: str | None = None


class Fonte(BaseModel):
    texto: str
    categoria: str | None
    data: str | None
    similaridade: float


class RespostaRag(BaseModel):
    resposta: str
    gerada_por_ia: bool
    fontes: list[Fonte]


# ---------- Dependências ----------

def _auth() -> SupabaseAuth:
    s = get_settings()
    return SupabaseAuth(s.supabase_url, s.supabase_key)


def repositorio(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> RepositorioSupabase:
    s = get_settings()
    return RepositorioSupabase(s.supabase_url, s.supabase_key, cred.credentials)


def _erro(e: ErroSupabase):
    # 401 = crachá vencido ou inválido (o app deve renovar a sessão).
    # 5xx do Supabase no cadastro = o trigger recusou o convite: para o app, é erro do pedido (400).
    raise HTTPException(status_code=400 if e.status >= 500 else e.status, detail=e.mensagem)


# ---------- Rotas ----------

@app.get("/saude")
def saude():
    return {"ok": True}


@app.post("/auth/cadastro", tags=["auth"])
def cadastro(dados: Cadastro, auth: SupabaseAuth = Depends(_auth)):
    try:
        return auth.cadastrar(dados.email, dados.senha, dados.convite)
    except ErroSupabase as e:
        _erro(e)


@app.post("/auth/login", tags=["auth"])
def login(dados: Login, auth: SupabaseAuth = Depends(_auth)):
    try:
        return auth.entrar(dados.email, dados.senha)
    except ErroSupabase as e:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos") from e


@app.post("/auth/renovar", tags=["auth"])
def renovar(dados: Renovar, auth: SupabaseAuth = Depends(_auth)):
    try:
        return auth.renovar(dados.refresh_token)
    except ErroSupabase as e:
        raise HTTPException(status_code=401, detail="Sessão expirada, faça login de novo") from e


@app.post("/memorias", tags=["memórias"], status_code=201)
def criar_memoria(dados: NovaMemoria, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        memoria_id, n = rag.alimentar(repo, dados.texto, dados.categoria, dados.data_evento)
        return {"id": memoria_id, "chunks": n}
    except ValueError as e:  # ex.: texto só com espaços
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ErroSupabase as e:
        _erro(e)


@app.get("/memorias", tags=["memórias"])
def listar_memorias(categoria: str | None = None, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        return repo.listar_memorias(categoria)
    except ErroSupabase as e:
        _erro(e)


@app.delete("/memorias/{memoria_id}", tags=["memórias"], status_code=204)
def apagar_memoria(memoria_id: str, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        if not repo.apagar_memoria(memoria_id):
            raise HTTPException(status_code=404, detail="Memória não encontrada")
    except ErroSupabase as e:
        _erro(e)


@app.post("/perguntar", tags=["perguntar"], response_model=RespostaRag)
def perguntar(dados: Pergunta, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        r = rag.perguntar(repo, dados.pergunta, dados.categoria)
    except ErroSupabase as e:
        _erro(e)
    return RespostaRag(
        resposta=r.texto,
        gerada_por_ia=r.gerada_por_ia,
        fontes=[
            Fonte(texto=t.texto, categoria=t.metadados.get("categoria"), data=t.metadados.get("data"),
                  similaridade=round(t.similaridade, 3))
            for t in r.fontes
        ],
    )


@app.post("/buscar", tags=["perguntar"], response_model=list[Fonte])
def buscar(dados: Pergunta, repo: RepositorioSupabase = Depends(repositorio)):
    """Só a busca, sem LLM: útil para entender se um problema está na busca ou na geração."""
    try:
        trechos = rag.buscar(repo, dados.pergunta, dados.categoria)
    except ErroSupabase as e:
        _erro(e)
    return [
        Fonte(texto=t.texto, categoria=t.metadados.get("categoria"), data=t.metadados.get("data"),
              similaridade=round(t.similaridade, 3))
        for t in trechos
    ]


# O app (PWA) é servido pela própria API, no endereço raiz. Fica por último para não
# "engolir" as rotas acima.
# Pasta do app: configurável (no Docker o pacote fica instalado longe do código-fonte).
_WEB = Path(os.getenv("LEMBRA_WEB_DIR") or Path(__file__).resolve().parents[2] / "web")
if _WEB.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")

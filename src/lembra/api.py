"""API do Lembra: os "endereços" que o app do celular chama.

Rodar:   uvicorn lembra.api:app --reload
Testar:  abra http://localhost:8000/docs (página interativa gerada automaticamente)

Toda rota de dados exige o cabeçalho  Authorization: Bearer <access_token>.
A API repassa esse crachá ao Supabase; quem decide o que a pessoa pode ver é o banco (RLS).
"""

from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from . import rag, whatsapp_bot
from .config import get_settings
from .supabase import ErroSupabase, RepositorioSupabase, SupabaseAuth, ping_banco

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
        except Exception as e:  # noqa: BLE001 — sem o modelo o app ainda abre; o erro aparece no 1º uso
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


class Login(BaseModel):
    email: EmailStr
    senha: str


class Renovar(BaseModel):
    refresh_token: str


class NovaMemoria(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    categoria: str = "geral"
    data_evento: str = ""


class EdicaoMemoria(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    categoria: str = "geral"
    data_evento: str = ""


class NovaCategoria(BaseModel):
    nome: str = Field(min_length=1, max_length=40)


class RenomearCategoria(BaseModel):
    novo_nome: str = Field(min_length=1, max_length=40)


class ConfigRag(BaseModel):
    # Mesmos limites do banco (validação dupla: aqui dá mensagem amigável; o banco é a garantia).
    chunk_size: int = Field(ge=200, le=3000)
    chunk_overlap: int = Field(ge=0)
    top_k: int = Field(ge=1, le=20)
    margem_relevancia: float = Field(ge=0, le=0.5)
    usar_ia: bool
    modo_agente: bool = False
    modelo_llm: str
    instrucoes: str = Field(default="", max_length=500)
    perfil_estilo: str = Field(default="", max_length=800)


class Feedback(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2000)
    resposta: str = Field(min_length=1, max_length=6000)
    util: bool
    comentario: str | None = Field(default=None, max_length=500)


class PreviaChunking(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)
    chunk_size: int = Field(ge=200, le=3000)
    chunk_overlap: int = Field(ge=0)


MODELOS_LLM = {
    "gemini-flash-lite-latest": "Gemini Flash-Lite: mais rápido, maior cota grátis",
    "gemini-flash-latest": "Gemini Flash: respostas mais elaboradas, cota grátis menor",
}


class ImportacaoWhatsApp(BaseModel):
    # UMA PARTE do arquivo (o app divide arquivos de até 10 MB em partes de ~300 KB; a Vercel
    # limita o corpo de cada requisição a 4,5 MB)
    conteudo: str = Field(min_length=1, max_length=3_000_000)
    nome_conversa: str = Field(min_length=1, max_length=80)
    categoria: str = Field(default="conversas", max_length=40)
    pausa_horas: float = Field(default=6, ge=0.5, le=72)
    confirmar: bool = False
    mes_primeiro: bool | None = None  # formato da data detectado pelo app no arquivo inteiro


class TextoMemoria(BaseModel):
    texto: str = Field(min_length=1, max_length=20_000)


class Audio(BaseModel):
    # base64 de até ~3 MB de áudio (≈ 2 min de voz comprimida); a Vercel limita o corpo a 4,5 MB
    audio_b64: str = Field(min_length=10, max_length=4_000_000)
    mime: str = Field(max_length=60)


class Turno(BaseModel):
    pergunta: str = Field(max_length=2_000)
    resposta: str = Field(max_length=6_000)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=2_000)
    categoria: str | None = None
    # últimas trocas da conversa (ficam só no aparelho; o servidor não guarda)
    historico: list[Turno] = Field(default_factory=list, max_length=6)


class Fonte(BaseModel):
    texto: str
    categoria: str | None
    data: str | None
    similaridade: float


class Passo(BaseModel):
    ferramenta: str
    argumentos: dict
    resumo: str


class RespostaRag(BaseModel):
    resposta: str
    gerada_por_ia: bool
    fontes: list[Fonte]
    passos: list[Passo] = []
    pergunta_entendida: str | None = None  # a pergunta reescrita com a conversa, se foi


# ---------- Dependências ----------

def _auth() -> SupabaseAuth:
    s = get_settings()
    return SupabaseAuth(s.supabase_url, s.supabase_key)


def repositorio(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> RepositorioSupabase:
    s = get_settings()
    return RepositorioSupabase(s.supabase_url, s.supabase_key, cred.credentials)


def _erro(e: ErroSupabase):
    # 401 = crachá vencido ou inválido (o app deve renovar a sessão).
    # 5xx vindo do Supabase = o BANCO está com problema (pausado, fora do ar): 503, "indisponível".
    raise HTTPException(status_code=503 if e.status >= 500 else e.status, detail=e.mensagem)


@app.exception_handler(Exception)
async def erro_interno(_request: Request, exc: Exception):
    """Qualquer erro inesperado: o traceback vai para o log do servidor e o app recebe o TIPO do erro
    (ex.: "ZoneInfoNotFoundError"), não o texto, que pode ter detalhes internos. Sem isso a tela só
    mostrava "Algo deu errado" e a causa ficava invisível para quem testa."""
    logger.exception("erro inesperado em %s", _request.url.path)
    return JSONResponse(status_code=500, content={"detail": f"Erro interno do servidor ({type(exc).__name__})."})


# ---------- Rotas ----------

@app.get("/saude")
def saude():
    return {"ok": True}


@app.get("/saude/banco")
def saude_banco():
    """Toca o banco. Chamada todo dia pelo cron da Vercel (vercel.json) para o projeto gratuito do
    Supabase não ser pausado por inatividade; também diz se o banco está no ar (503 se não estiver)."""
    s = get_settings()
    try:
        ping_banco(s.supabase_url, s.supabase_key)
    except ErroSupabase as e:
        _erro(e)
    return {"banco": "ok"}


@app.post("/auth/cadastro", tags=["auth"])
def cadastro(dados: Cadastro, auth: SupabaseAuth = Depends(_auth)):
    try:
        return auth.cadastrar(dados.email, dados.senha)
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


@app.put("/memorias/{memoria_id}", tags=["memórias"])
def editar_memoria(memoria_id: str, dados: EdicaoMemoria, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        r = rag.editar(repo, memoria_id, dados.texto, dados.categoria, dados.data_evento)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ErroSupabase as e:
        _erro(e)
    if r is None:
        raise HTTPException(status_code=404, detail="Memória não encontrada")
    return r


@app.get("/memorias/{memoria_id}/chunks", tags=["laboratório"])
def chunks_da_memoria(memoria_id: str, repo: RepositorioSupabase = Depends(repositorio)):
    """Laboratório: como esta memória foi quebrada em chunks."""
    try:
        return repo.listar_chunks(memoria_id)
    except ErroSupabase as e:
        _erro(e)


@app.get("/config", tags=["laboratório"])
def ler_config(repo: RepositorioSupabase = Depends(repositorio)):
    """Configuração efetiva do usuário (padrões do servidor + o que ele ajustou)."""
    try:
        s = rag.settings_do_usuario(repo)
    except ErroSupabase as e:
        _erro(e)
    return {
        "chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap, "top_k": s.top_k,
        "margem_relevancia": s.margem_relevancia, "usar_ia": s.usar_ia, "modo_agente": s.modo_agente,
        "modelo_llm": s.gemini_model, "instrucoes": s.instrucoes, "perfil_estilo": s.perfil_estilo,
        "modelos_llm": MODELOS_LLM,
        "somente_leitura": {"modelo_embedding": s.embedding_model, "dimensao_embedding": s.embedding_dim,
                            "provedor_llm": s.llm_provider},
    }


@app.put("/config", tags=["laboratório"])
def salvar_config(dados: ConfigRag, repo: RepositorioSupabase = Depends(repositorio)):
    if dados.chunk_overlap * 2 >= dados.chunk_size:
        raise HTTPException(status_code=400, detail="A sobreposição precisa ser menor que metade do chunk.")
    if dados.modelo_llm not in MODELOS_LLM:
        raise HTTPException(status_code=400, detail="Modelo de IA desconhecido.")
    try:
        return repo.salvar_config(dados.model_dump())
    except ErroSupabase as e:
        _erro(e)


@app.post("/feedback", tags=["personalização"])
def enviar_feedback(dados: Feedback, repo: RepositorioSupabase = Depends(repositorio)):
    """👍/👎 numa resposta. A cada 5 avaliações novas, o perfil de estilo é reaprendido."""
    try:
        return rag.registrar_feedback(repo, dados.pergunta, dados.resposta, dados.util, dados.comentario)
    except ErroSupabase as e:
        _erro(e)


@app.post("/perfil/aprender", tags=["personalização"])
def aprender_perfil(repo: RepositorioSupabase = Depends(repositorio)):
    """Reescreve agora o perfil de estilo a partir das memórias e avaliações."""
    try:
        perfil = rag.aprender_perfil(repo)
    except ErroSupabase as e:
        _erro(e)
    if perfil is None:
        raise HTTPException(status_code=400, detail="Ainda não há dados suficientes (ou a IA está desligada).")
    return {"perfil_estilo": perfil}


@app.post("/lab/chunking", tags=["laboratório"])
def previa_chunking(dados: PreviaChunking, _cred: HTTPAuthorizationCredentials = Depends(_bearer)):
    """Mostra como um texto SERIA quebrado, sem salvar nada. Exige login, como os demais
    endpoints que fazem trabalho no servidor (evita uso anônimo da CPU)."""
    if dados.chunk_overlap * 2 >= dados.chunk_size:
        raise HTTPException(status_code=400, detail="A sobreposição precisa ser menor que metade do chunk.")
    chunks = rag.previa_chunking(dados.texto, dados.chunk_size, dados.chunk_overlap)
    return {"chunks": chunks, "total": len(chunks), "tamanhos": [len(c) for c in chunks]}


@app.post("/memorias/reprocessar", tags=["laboratório"])
def reprocessar(repo: RepositorioSupabase = Depends(repositorio)):
    """Refaz chunks e vetores de todas as memórias com a configuração atual."""
    try:
        return rag.reprocessar(repo)
    except ErroSupabase as e:
        _erro(e)


@app.post("/importar/whatsapp", tags=["importar"])
def importar_whatsapp(dados: ImportacaoWhatsApp, repo: RepositorioSupabase = Depends(repositorio)):
    """Importa uma conversa exportada do WhatsApp (.txt). Sem `confirmar`, devolve só a prévia."""
    try:
        return rag.importar_conversa(repo, dados.conteudo, dados.nome_conversa.strip(), dados.categoria,
                                     dados.pausa_horas, dados.confirmar, mes_primeiro=dados.mes_primeiro)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ErroSupabase as e:
        _erro(e)


@app.post("/categorias/sugerir", tags=["categorias"])
def sugerir_categoria(dados: TextoMemoria, repo: RepositorioSupabase = Depends(repositorio)):
    """A IA sugere uma categoria (existente ou nova) para o texto. {} se não houver sugestão."""
    try:
        return rag.sugerir_categoria(repo, dados.texto) or {}
    except ErroSupabase as e:
        _erro(e)


@app.post("/audio/transcrever", tags=["áudio"])
def transcrever(dados: Audio, repo: RepositorioSupabase = Depends(repositorio)):
    """Transforma áudio gravado no app em texto. O áudio não é guardado."""
    import base64
    import binascii

    try:
        audio = base64.b64decode(dados.audio_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(status_code=400, detail="Áudio inválido") from e
    try:
        return {"texto": rag.transcrever_audio(repo, audio, dados.mime)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ErroSupabase as e:
        _erro(e)
    except Exception as e:  # serviço de IA indisponível/limite
        logger.warning("transcrição falhou: %s", e)
        raise HTTPException(status_code=503, detail="Não consegui transcrever agora. Tente de novo em instantes.") from e


@app.get("/categorias", tags=["categorias"])
def listar_categorias(repo: RepositorioSupabase = Depends(repositorio)):
    try:
        return repo.listar_categorias()
    except ErroSupabase as e:
        _erro(e)


@app.post("/categorias", tags=["categorias"], status_code=201)
def criar_categoria(dados: NovaCategoria, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        repo.criar_categoria(dados.nome)
    except ErroSupabase as e:
        _erro(e)
    return {"nome": dados.nome.strip().lower()}


@app.put("/categorias/{nome}", tags=["categorias"])
def renomear_categoria(nome: str, dados: RenomearCategoria, repo: RepositorioSupabase = Depends(repositorio)):
    try:
        repo.renomear_categoria(nome, dados.novo_nome)
    except ErroSupabase as e:
        _erro(e)
    return {"nome": dados.novo_nome.strip().lower()}


@app.delete("/categorias/{nome}", tags=["categorias"])
def apagar_categoria(nome: str, mover_para: str = "geral", repo: RepositorioSupabase = Depends(repositorio)):
    """Apaga a categoria; as memórias dela são MOVIDAS para `mover_para`, nunca apagadas."""
    try:
        return {"memorias_movidas": repo.apagar_categoria(nome, mover_para)}
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
        r = rag.perguntar(repo, dados.pergunta, dados.categoria,
                          historico=[t.model_dump() for t in dados.historico])
    except ErroSupabase as e:
        _erro(e)
    return RespostaRag(
        resposta=r.texto,
        gerada_por_ia=r.gerada_por_ia,
        passos=[Passo(**p) for p in r.passos],
        pergunta_entendida=r.pergunta_entendida,
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


# ---------- Minha conta (LGPD: portabilidade e eliminação) ----------

class ApagarConta(BaseModel):
    senha: str = Field(min_length=1, max_length=200)
    confirmacao: str = Field(max_length=20)


@app.get("/conta/exportar", tags=["conta"])
def exportar_conta(repo: RepositorioSupabase = Depends(repositorio)):
    """Tudo o que o Lembra guarda desta pessoa, em JSON (baixado pelo app)."""
    try:
        dados = repo.exportar_tudo()
    except ErroSupabase as e:
        _erro(e)
    return JSONResponse(
        {"exportado_em": datetime.now(UTC).isoformat(timespec="seconds"), **dados},
        headers={"Content-Disposition": 'attachment; filename="lembra-meus-dados.json"'})


@app.delete("/conta", tags=["conta"], status_code=204)
def apagar_conta(dados: ApagarConta, cred: HTTPAuthorizationCredentials = Depends(_bearer),
                 auth: SupabaseAuth = Depends(_auth), repo: RepositorioSupabase = Depends(repositorio)):
    """Apaga a conta e TODOS os dados. Ação irreversível: exige digitar APAGAR e a SENHA de novo
    (reautenticação: um celular desbloqueado com o app aberto não basta)."""
    if dados.confirmacao.strip() != "APAGAR":
        raise HTTPException(status_code=400, detail='Digite APAGAR para confirmar.')
    try:
        email = auth.email_de(cred.credentials)
        try:
            auth.entrar(email, dados.senha)
        except ErroSupabase as e:
            if e.status in (400, 401, 422):
                raise HTTPException(status_code=403, detail="Senha incorreta.") from e
            raise
        repo.apagar_conta()
    except ErroSupabase as e:
        _erro(e)


# ---------- WhatsApp (bot oficial) ----------

@app.get("/whatsapp/webhook", tags=["whatsapp"], response_class=PlainTextResponse)
def whatsapp_verificar(
    modo: str = Query("", alias="hub.mode"), token: str = Query("", alias="hub.verify_token"),
    desafio: str = Query("", alias="hub.challenge"),
):
    """Cadastro do webhook: a Meta manda um token combinado; devolvemos o "desafio" se bater."""
    cfg = whatsapp_bot.ConfigWhatsApp.do_ambiente()
    if modo == "subscribe" and cfg.verify_token and hmac.compare_digest(token, cfg.verify_token):
        return desafio
    raise HTTPException(status_code=403, detail="Token de verificação inválido")


@app.post("/whatsapp/webhook", tags=["whatsapp"])
async def whatsapp_receber(request: Request):
    """Mensagens recebidas. Sem crachá de usuário: quem prova a origem é a ASSINATURA da Meta."""
    cfg = whatsapp_bot.ConfigWhatsApp.do_ambiente()
    if not cfg.completa:
        raise HTTPException(status_code=503, detail="WhatsApp não configurado no servidor")
    corpo = await request.body()  # bytes EXATOS: a assinatura é sobre eles, não sobre o JSON
    if not whatsapp_bot.assinatura_valida(corpo, request.headers.get("X-Hub-Signature-256"), cfg.app_secret):
        raise HTTPException(status_code=401, detail="Assinatura inválida")
    s = get_settings()
    banco = whatsapp_bot.BancoDoBot(s.supabase_url, s.supabase_key, cfg.jwt_secret)
    meta = whatsapp_bot.MetaWhatsApp(cfg.token, cfg.phone_id)
    # roda numa thread: o processamento faz chamadas de rede bloqueantes (Supabase, Gemini, Meta)
    tratadas = await run_in_threadpool(whatsapp_bot.processar_webhook, json.loads(corpo), banco, meta)
    return {"tratadas": tratadas}


@app.get("/whatsapp/vinculo", tags=["whatsapp"])
def whatsapp_vinculo(repo: RepositorioSupabase = Depends(repositorio)):
    """Número ligado à conta (ou null) e o número do Lembra, para o app mostrar."""
    try:
        return {"vinculo": repo.vinculo_whatsapp(), "numero_lembra": os.getenv("WHATSAPP_NUMERO", "")}
    except ErroSupabase as e:
        _erro(e)


@app.post("/whatsapp/codigo", tags=["whatsapp"])
def whatsapp_codigo(repo: RepositorioSupabase = Depends(repositorio)):
    """Código de uso único (10 min) para enviar ao bot: VINCULAR <código>."""
    try:
        return {"codigo": repo.gerar_codigo_whatsapp(), "validade_minutos": 10}
    except ErroSupabase as e:
        _erro(e)


@app.delete("/whatsapp/vinculo", tags=["whatsapp"], status_code=204)
def whatsapp_desvincular(repo: RepositorioSupabase = Depends(repositorio)):
    try:
        repo.desvincular_whatsapp()
    except ErroSupabase as e:
        _erro(e)


# O app (PWA) é servido pela própria API, no endereço raiz. Fica por último para não
# "engolir" as rotas acima.
# Pasta do app: configurável (no Docker o pacote fica instalado longe do código-fonte).
_WEB = Path(os.getenv("LEMBRA_WEB_DIR") or Path(__file__).resolve().parents[2] / "web")
if _WEB.is_dir():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_WEB, html=True), name="web")

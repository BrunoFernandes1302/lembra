"""Lembra no WhatsApp (API oficial da Meta, "Cloud API").

Fluxo: a pessoa manda mensagem para o número do Lembra -> a Meta chama nosso WEBHOOK
(POST /whatsapp/webhook) -> conferimos a assinatura -> descobrimos o dono do número ->
agimos COMO ele (crachá emitido por nós, então o RLS continua protegendo) -> respondemos.

Regras simples, decididas pelo código (previsível, grátis e instantâneo):
- "VINCULAR ABCD2345" -> liga este número à conta que gerou o código no app;
- termina (ou começa) com "?" -> pergunta ao RAG;
- "ajuda" -> instruções;
- qualquer outro texto -> vira memória (a IA sugere a categoria);
- áudio -> transcrito e tratado como texto.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass

from lembra import rag
from lembra.supabase import TIMEOUT, ErroSupabase, RepositorioSupabase, _checar, _http

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com/v25.0"
LIMITE_WHATSAPP = 4096  # caracteres por mensagem de texto

AJUDA = (
    "Oi! Eu sou o *Lembra* 🧠\n\n"
    "• Escreva algo e eu *guardo* como memória.\n"
    "• Termine com *?* para *perguntar* (ex.: _quando é o dentista?_).\n"
    "• Pode mandar *áudio* também.\n"
    "• *ajuda* mostra esta mensagem."
)
NAO_VINCULADO = (
    "Este número ainda não está ligado a uma conta do Lembra.\n\n"
    "No app: *Ajustes → WhatsApp → Gerar código* e envie aqui: *VINCULAR SEUCODIGO*"
)


@dataclass(frozen=True)
class ConfigWhatsApp:
    token: str          # token de acesso da Meta (para enviar mensagens e baixar áudios)
    phone_id: str       # id do número do Lembra na Meta
    app_secret: str     # segredo do app Meta: confere a assinatura de cada webhook
    verify_token: str   # combinado com a Meta na hora de cadastrar o webhook
    jwt_secret: str     # segredo do Supabase que assina os crachás (Legacy JWT secret)

    @classmethod
    def do_ambiente(cls) -> ConfigWhatsApp:
        return cls(
            token=os.getenv("WHATSAPP_TOKEN", ""),
            phone_id=os.getenv("WHATSAPP_PHONE_ID", ""),
            app_secret=os.getenv("WHATSAPP_APP_SECRET", ""),
            verify_token=os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
            jwt_secret=os.getenv("SUPABASE_JWT_SECRET", ""),
        )

    @property
    def completa(self) -> bool:
        return all((self.token, self.phone_id, self.app_secret, self.verify_token, self.jwt_secret))


# ---------------------------------------------------------------- segurança
def assinatura_valida(corpo: bytes, cabecalho: str | None, segredo: str) -> bool:
    """A Meta assina o corpo com HMAC-SHA256 usando o segredo do app (X-Hub-Signature-256).
    Recalculamos e comparamos em TEMPO CONSTANTE (compare_digest): uma comparação comum para
    na 1ª letra diferente, e o tempo de resposta vazaria a assinatura aos poucos."""
    if not segredo or not cabecalho or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho.removeprefix("sha256="))


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def emitir_jwt(segredo: str, papel: str, sub: str | None = None, validade: int = 300) -> str:
    """Um JWT é só cabeçalho.conteúdo.assinatura (base64). Quem tem o segredo assina; o
    Supabase confere a assinatura e passa a tratar a chamada como `papel` (e `sub` vira o
    auth.uid() das políticas RLS). Vida curta: se vazar, expira em minutos."""
    agora = int(time.time())
    conteudo = {"role": papel, "iat": agora, "exp": agora + validade}
    if sub:
        conteudo |= {"sub": sub, "aud": "authenticated"}
    partes = [_b64(json.dumps(p, separators=(",", ":")).encode())
              for p in ({"alg": "HS256", "typ": "JWT"}, conteudo)]
    base = ".".join(partes)
    assinatura = hmac.new(segredo.encode(), base.encode(), hashlib.sha256).digest()
    return f"{base}.{_b64(assinatura)}"


# ---------------------------------------------------------------- mensagens
@dataclass
class MensagemRecebida:
    id: str
    telefone: str
    tipo: str          # "text", "audio" ou outro (imagem, figurinha... ainda não tratados)
    texto: str = ""
    midia_id: str = ""
    mime: str = ""


def extrair_mensagens(payload: dict) -> list[MensagemRecebida]:
    """O webhook traz entry[].changes[].value.messages[]. Avisos de status (entregue, lido)
    vêm em value.statuses e são ignorados."""
    saida = []
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for m in mudanca.get("value", {}).get("messages", []) or []:
                tipo = m.get("type", "")
                msg = MensagemRecebida(id=m.get("id", ""), telefone=m.get("from", ""), tipo=tipo)
                if tipo == "text":
                    msg.texto = m.get("text", {}).get("body", "")
                elif tipo == "audio":
                    msg.midia_id = m.get("audio", {}).get("id", "")
                    msg.mime = m.get("audio", {}).get("mime_type", "audio/ogg")
                if msg.id and msg.telefone:
                    saida.append(msg)
    return saida


def extrair_falhas(payload: dict) -> list[dict]:
    """Avisos de status "failed": a Meta aceitou o envio, mas não conseguiu entregar. Guardamos só
    o código e o motivo (sem conteúdo nem número) para diagnosticar."""
    falhas = []
    for entrada in payload.get("entry", []):
        for mudanca in entrada.get("changes", []):
            for st in mudanca.get("value", {}).get("statuses", []) or []:
                if st.get("status") != "failed":
                    continue
                for e in st.get("errors") or [{}]:
                    falhas.append({"codigo": e.get("code"), "titulo": e.get("title") or e.get("message") or "",
                                   "detalhe": (e.get("error_data") or {}).get("details", "")})
    return falhas


_VINCULAR = re.compile(r"^\s*vincular\s+([A-Za-z0-9]{6,12})\s*$", re.IGNORECASE)
_AJUDA = {"ajuda", "help", "menu", "oi", "olá", "ola", "comandos"}


def classificar(texto: str) -> tuple[str, str]:
    """Decide a ação pelo TEXTO, sem IA. Devolve (ação, conteúdo)."""
    if m := _VINCULAR.match(texto):
        return "vincular", m[1].upper()
    t = texto.strip()
    if t.lower().strip("!.") in _AJUDA:
        return "ajuda", ""
    if t.endswith("?") or t.startswith("?"):
        return "pergunta", t.lstrip("?").strip()
    return "memoria", t


# ---------------------------------------------------------------- serviços externos
class BancoDoBot:
    """O que o bot faz no banco SEM ser um usuário: só as 3 funções liberadas ao service_role."""

    def __init__(self, url: str, chave_publica: str, jwt_secret: str):
        self.url = url.rstrip("/")
        self.chave_publica = chave_publica
        self.jwt_secret = jwt_secret

    def _rpc(self, funcao: str, args: dict):
        cabecalhos = {"apikey": self.chave_publica, "Content-Type": "application/json",
                      "Authorization": f"Bearer {emitir_jwt(self.jwt_secret, 'service_role', validade=60)}"}
        r = _http.post(f"{self.url}/rest/v1/rpc/{funcao}", headers=cabecalhos, json=args, timeout=TIMEOUT)
        return _checar(r)

    def primeira_vez(self, mensagem_id: str) -> bool:
        return bool(self._rpc("whatsapp_marcar_processada", {"p_id": mensagem_id}))

    def dono(self, telefone: str) -> str | None:
        return self._rpc("whatsapp_dono", {"p_telefone": telefone})

    def vincular(self, codigo: str, telefone: str) -> str | None:
        return self._rpc("whatsapp_vincular", {"p_codigo": codigo, "p_telefone": telefone})

    def registrar_falha(self, codigo: int | None, titulo: str, detalhe: str) -> None:
        self._rpc("whatsapp_registrar_falha", {"p_codigo": codigo, "p_titulo": titulo, "p_detalhe": detalhe})

    def repositorio_de(self, user_id: str) -> RepositorioSupabase:
        """Crachá de 5 min DAQUELE usuário: a partir daqui, o RLS limita tudo às memórias dele."""
        token = emitir_jwt(self.jwt_secret, "authenticated", sub=user_id)
        return RepositorioSupabase(self.url, self.chave_publica, token)


def numero_para_envio(telefone: str) -> str:
    """Celulares brasileiros: o WhatsApp entrega o remetente no formato ANTIGO, sem o 9º dígito
    (55 + DDD + 8 dígitos), mas a Meta só aceita enviar para o número completo, com o 9
    (senão: erro 131030, "não está na lista permitida"). Só mexe em celular (começa com 6-9);
    fixo e outros países passam intactos. O vínculo continua usando o número como veio."""
    if len(telefone) == 12 and telefone.startswith("55") and telefone[4] in "6789":
        return telefone[:4] + "9" + telefone[4:]
    return telefone


class MetaWhatsApp:
    """Enviar mensagens e baixar áudios pela Graph API da Meta."""

    def __init__(self, token: str, phone_id: str):
        self.phone_id = phone_id
        self.cabecalhos = {"Authorization": f"Bearer {token}"}

    def enviar(self, telefone: str, texto: str) -> dict | None:
        """Envia e devolve None se a Meta aceitou, ou {codigo, titulo, detalhe} se recusou na hora."""
        corpo = {"messaging_product": "whatsapp", "to": numero_para_envio(telefone), "type": "text",
                 "text": {"body": texto[:LIMITE_WHATSAPP]}}
        r = _http.post(f"{GRAPH}/{self.phone_id}/messages", headers=self.cabecalhos, json=corpo, timeout=TIMEOUT)
        if r.ok:
            return None
        logger.warning("Meta recusou o envio (%s): %s", r.status_code, r.text[:300])
        try:
            erro = r.json().get("error", {})
        except ValueError:
            erro = {}
        return {"codigo": erro.get("code") or r.status_code, "titulo": erro.get("message") or "recusado",
                "detalhe": (erro.get("error_data") or {}).get("details", "")}

    def baixar_midia(self, midia_id: str) -> bytes:
        """Dois passos: o id vira uma URL temporária; a URL (com o token) devolve o arquivo."""
        info = _http.get(f"{GRAPH}/{midia_id}", headers=self.cabecalhos, timeout=TIMEOUT)
        info.raise_for_status()
        arquivo = _http.get(info.json()["url"], headers=self.cabecalhos, timeout=TIMEOUT)
        arquivo.raise_for_status()
        return arquivo.content


# ---------------------------------------------------------------- orquestração
def _resumo_fontes(resposta: rag.Resposta) -> str:
    if not resposta.fontes:
        return ""
    datas = sorted({f.metadados.get("data") or "" for f in resposta.fontes} - {""})
    rodape = f"\n\n_📚 {len(resposta.fontes)} memória(s) consultada(s)"
    return rodape + (f", de {datas[0]}" + (f" a {datas[-1]}" if len(datas) > 1 else "") if datas else "") + "_"


def responder(msg: MensagemRecebida, banco: BancoDoBot, meta: MetaWhatsApp) -> str | None:
    """Processa UMA mensagem e devolve o texto da resposta (None = não responder)."""
    if not banco.primeira_vez(msg.id):
        return None  # reenvio da Meta: já tratamos esta mensagem

    if msg.tipo == "text":
        acao, conteudo = classificar(msg.texto)
        if acao == "vincular":
            try:
                ok = banco.vincular(conteudo, msg.telefone)
            except ErroSupabase as e:
                if "muitas tentativas" in e.mensagem:  # o único erro "de produto" desta função
                    return "⏳ Muitas tentativas com código errado. Aguarde uma hora e gere um código novo."
                logger.exception("falha ao vincular")  # detalhe interno: vai para o log, não para o usuário
                return "😕 Não consegui vincular agora. Tente de novo em instantes."
            return ("✅ Pronto! Este WhatsApp está ligado à sua conta do Lembra.\n\n" + AJUDA) if ok else \
                   "❌ Código inválido ou expirado. Gere outro no app (vale 10 minutos)."

    dono = banco.dono(msg.telefone)
    if dono is None:
        return NAO_VINCULADO
    repo = banco.repositorio_de(dono)

    prefixo = ""
    if msg.tipo == "audio":
        try:
            texto = rag.transcrever_audio(repo, meta.baixar_midia(msg.midia_id), msg.mime)
        except ValueError as e:
            return f"Não consegui usar o áudio: {e}"
        if not texto.strip():
            return "Não ouvi nenhuma fala no áudio 🤔"
        prefixo = f"🎙️ _{texto.strip()[:300]}_\n\n"
        acao, conteudo = classificar(texto)
    elif msg.tipo != "text":
        return "Por enquanto eu entendo *texto* e *áudio* 🙂"

    if acao == "ajuda":
        return AJUDA
    if acao == "pergunta":
        resposta = rag.perguntar(repo, conteudo)
        return prefixo + resposta.texto + _resumo_fontes(resposta)
    if acao == "vincular":  # "vincular" falado num áudio: só por texto, para evitar engano
        return "Para vincular, envie o código por *texto*."
    sugestao = rag.sugerir_categoria(repo, conteudo)
    categoria = sugestao["categoria"] if sugestao else "geral"
    if sugestao and sugestao["nova"]:
        repo.criar_categoria(categoria)
    rag.alimentar(repo, conteudo, categoria)
    return prefixo + f"✅ Guardei em *{categoria}*."


def processar_webhook(payload: dict, banco: BancoDoBot, meta: MetaWhatsApp) -> int:
    """Trata todas as mensagens do envio; um erro numa mensagem não impede as outras."""
    def registrar(falha: dict) -> None:
        logger.warning("Meta não entregou uma resposta: %s", falha)
        try:
            banco.registrar_falha(falha["codigo"], falha["titulo"], falha["detalhe"])
        except ErroSupabase:
            logger.exception("não consegui registrar a falha de entrega")

    for falha in extrair_falhas(payload):  # recusas DEPOIS de aceitar (aviso de status "failed")
        registrar(falha)
    tratadas = 0
    for msg in extrair_mensagens(payload):
        try:
            texto = responder(msg, banco, meta)
        except Exception:  # responde algo em vez de deixar a pessoa sem retorno (o erro vai pro log)
            logger.exception("falha ao tratar mensagem %s", msg.id)
            texto = "😕 Tive um problema para processar isso. Tente de novo em instantes."
        if texto:
            recusa = meta.enviar(msg.telefone, texto)  # recusa NA HORA (ex.: número fora da lista)
            if recusa:
                registrar(recusa)
            tratadas += 1
    return tratadas

"""Importação de conversas exportadas do WhatsApp (Conversa → ⋮ → Mais → Exportar conversa → Sem mídia).

Por que exportar? A API oficial do WhatsApp não lê conversas pessoais (só mensagens enviadas a
um número de empresa). Exportar é o caminho oficial: o próprio usuário escolhe QUAIS conversas
entram no Lembra.

Formatos (variam por sistema e idioma):
  Android:  03/11/2026 14:05 - João: vamos sexta?
  iPhone:   [03/11/2026, 14:05:22] João: vamos sexta?
Mensagens com várias linhas continuam nas linhas seguintes, sem cabeçalho.

Chunking de CONVERSA (diferente de texto corrido):
  - quebra em "sessões": se passaram mais de `pausa_horas` sem mensagem, começa um bloco novo
    (assuntos mudam com o tempo);
  - blocos muito longos são divididos pelo tamanho máximo, sempre entre mensagens;
  - cada bloco vira uma memória com a DATA como metadado e "Autor: texto" em cada linha.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# Cabeçalho de mensagem: Android "dd/mm/aaaa hh:mm - " ou iPhone "[dd/mm/aaaa, hh:mm:ss] ".
# Aparelhos em inglês usam mês/dia e relógio de 12 h ("3/11/26, 2:05 PM - ").
_CABECALHO = re.compile(
    r"^‎?\[?(?P<data>\d{1,2}/\d{1,2}/\d{2,4}),?\s+(?P<hora>\d{1,2}:\d{2})(?::\d{2})?"
    r"\s*(?:(?P<ampm>[aApP])\.?\s?[mM]\.?)?\]?\s*(?:-\s*)?(?P<resto>.*)$"
)
# Mensagens que são ruído (sem informação útil para o Lembra)
_RUIDO = re.compile(
    r"(<m[íi]dia oculta>|<media omitted>|m[íi]dia oculta|imagem ocultada|v[íi]deo omitido|"
    r"[áa]udio ocultado|figurinha omitida|sticker omitted|documento omitido|<attached:|"
    r"mensagem apagada|this message was deleted|voc[êe] apagou esta mensagem|"
    r"esta mensagem foi editada|<esta mensagem foi editada>|null)\s*$",
    re.IGNORECASE,
)


@dataclass
class Mensagem:
    quando: datetime
    autor: str
    texto: str


@dataclass
class Bloco:
    inicio: datetime
    fim: datetime
    mensagens: list[Mensagem]

    @property
    def autores(self) -> list[str]:
        return sorted({m.autor for m in self.mensagens})

    def como_texto(self) -> str:
        return "\n".join(f"{m.autor}: {m.texto}" for m in self.mensagens)


def _mes_primeiro(linhas: list[str]) -> bool:
    """Detecta o formato do ARQUIVO inteiro: se alguma data tem o 2º número > 12, ele só pode
    ser o dia, então o arquivo é mês/dia (aparelhos em inglês). Caso contrário, dia/mês."""
    for linha in linhas:
        c = _CABECALHO.match(linha)
        if c and int(c["data"].split("/")[1]) > 12:
            return True
    return False


def _data(data: str, hora: str, ampm: str | None = None, mes_primeiro: bool = False) -> datetime | None:
    p1, p2, a = data.split("/")
    d, m = (p2, p1) if mes_primeiro else (p1, p2)
    a = ("20" + a) if len(a) == 2 else a
    h, minuto = map(int, hora.split(":"))
    if ampm:  # relógio de 12 h: 12 AM = 0 h; 1-11 PM = 13-23 h
        h = h % 12 + (12 if ampm.lower() == "p" else 0)
    try:
        return datetime(int(a), int(m), int(d), h, minuto)
    except ValueError:
        return None


def ler_exportacao(conteudo: str, mes_primeiro: bool | None = None) -> list[Mensagem]:
    """Transforma o .txt exportado em mensagens (autor, quando, texto), descartando ruído.
    mes_primeiro: formato da data já detectado no ARQUIVO INTEIRO (quando o app divide um
    arquivo grande em partes, uma parte sozinha pode não revelar se é dia/mês ou mês/dia)."""
    mensagens: list[Mensagem] = []
    atual: Mensagem | None = None
    linhas = [ln.replace("‎", "").replace(" ", " ").rstrip()
              for ln in conteudo.replace("\r\n", "\n").split("\n")]
    if mes_primeiro is None:
        mes_primeiro = _mes_primeiro(linhas)
    for linha in linhas:
        c = _CABECALHO.match(linha)
        quando = _data(c["data"], c["hora"], c["ampm"], mes_primeiro) if c else None
        if c and quando:
            atual = None
            resto = c["resto"]
            if ": " not in resto:  # aviso do sistema (criptografia, "fulano entrou", etc.)
                continue
            autor, texto = resto.split(": ", 1)
            atual = Mensagem(quando, autor.strip(), texto.strip())
            mensagens.append(atual)
        elif atual is not None and linha.strip():
            atual.texto += "\n" + linha.strip()  # continuação de mensagem com várias linhas
    return [m for m in mensagens if m.texto and not _RUIDO.search(m.texto)]


def agrupar(mensagens: list[Mensagem], pausa_horas: float = 6, max_caracteres: int = 1500) -> list[Bloco]:
    """Agrupa mensagens em blocos de conversa (sessões), sem cortar mensagens ao meio."""
    blocos: list[Bloco] = []
    pausa = timedelta(hours=pausa_horas)
    tamanho = 0
    for m in mensagens:
        linha = len(m.autor) + len(m.texto) + 3
        novo = not blocos or m.quando - blocos[-1].fim > pausa or tamanho + linha > max_caracteres
        if novo:
            blocos.append(Bloco(m.quando, m.quando, []))
            tamanho = 0
        blocos[-1].mensagens.append(m)
        blocos[-1].fim = m.quando
        tamanho += linha
    return blocos


def texto_da_memoria(bloco: Bloco, nome_conversa: str) -> str:
    """O texto que vira memória: um cabeçalho de contexto + as falas.
    O cabeçalho ajuda a busca: "conversa com João em 03/11/2026" aparece no próprio texto."""
    quando = bloco.inicio.strftime("%d/%m/%Y")
    hora = f"{bloco.inicio:%H:%M}–{bloco.fim:%H:%M}"
    return (f"Conversa de WhatsApp \"{nome_conversa}\" em {quando} ({hora}), "
            f"entre {', '.join(bloco.autores)}:\n{bloco.como_texto()}")

from lembra.whatsapp import agrupar, ler_exportacao, texto_da_memoria

ANDROID = """03/11/2026 09:00 - As mensagens e as ligações são protegidas com a criptografia de ponta a ponta.
03/11/2026 09:01 - João Silva: Bom dia! Bora viajar em dezembro?
03/11/2026 09:02 - Bruno: Bora! Pensei em Floripa
03/11/2026 09:03 - João Silva: <Mídia oculta>
03/11/2026 09:05 - João Silva: Fechado. Eu levo a barraca
e você leva o fogareiro
03/11/2026 09:06 - Bruno: Mensagem apagada
04/11/2026 20:15 - Bruno: Reservei a pousada: 650 reais por 3 noites"""

IPHONE = """[03/11/2026, 09:01:12] João Silva: Bom dia! Bora viajar em dezembro?
[03/11/2026, 09:02:40] Bruno: Bora! Pensei em Floripa
[03/11/2026, 09:05:01] João Silva: ‎imagem ocultada
[04/11/2026, 20:15:33] Bruno: Reservei a pousada"""


def test_android_ignora_ruido_e_junta_linhas():
    msgs = ler_exportacao(ANDROID)
    assert [m.autor for m in msgs] == ["João Silva", "Bruno", "João Silva", "Bruno"]
    assert msgs[2].texto == "Fechado. Eu levo a barraca\ne você leva o fogareiro"
    assert all("Mídia" not in m.texto and "apagada" not in m.texto for m in msgs)


def test_iphone():
    msgs = ler_exportacao(IPHONE)
    assert len(msgs) == 3 and msgs[0].quando.hour == 9 and msgs[-1].texto == "Reservei a pousada"


def test_agrupa_por_pausa_longa():
    blocos = agrupar(ler_exportacao(ANDROID), pausa_horas=6)
    assert len(blocos) == 2, "a mensagem do dia seguinte começa outra sessão"
    assert blocos[0].autores == ["Bruno", "João Silva"]


def test_bloco_grande_e_dividido_entre_mensagens():
    linhas = "\n".join(f"03/11/2026 10:{i:02d} - Ana: mensagem número {i} com algum texto" for i in range(50))
    blocos = agrupar(ler_exportacao(linhas), max_caracteres=300)
    assert len(blocos) > 1
    assert sum(len(b.mensagens) for b in blocos) == 50, "nenhuma mensagem se perde"


def test_texto_da_memoria_tem_contexto():
    b = agrupar(ler_exportacao(ANDROID))[0]
    t = texto_da_memoria(b, "Viagem com João")
    assert t.startswith('Conversa de WhatsApp "Viagem com João" em 03/11/2026')
    assert "João Silva: Bora viajar" not in t and "João Silva: Bom dia! Bora viajar em dezembro?" in t


def test_relogio_de_12_horas_e_formato_mes_dia():
    # aparelho em inglês: mês/dia e AM/PM ("11/23" só pode ser mês 11, dia 23)
    conversa = """11/23/26, 2:05 PM - Ann: See you at the dentist
11/23/26, 12:10 AM - Bob: ok
11/3/26, 9:00 AM - Ann: earlier"""
    msgs = ler_exportacao(conversa)
    assert (msgs[0].quando.month, msgs[0].quando.day, msgs[0].quando.hour) == (11, 23, 14), "2:05 PM = 14h"
    assert msgs[1].quando.hour == 0, "12:10 AM = meia-noite"
    assert (msgs[2].quando.month, msgs[2].quando.day) == (11, 3), "o formato vale para o arquivo inteiro"


def test_padrao_brasileiro_continua_dia_mes():
    msgs = ler_exportacao("03/11/2026 14:05 - Ana: oi\n04/11/2026 09:00 - Ana: bom dia")
    assert (msgs[0].quando.day, msgs[0].quando.month, msgs[0].quando.hour) == (3, 11, 14)

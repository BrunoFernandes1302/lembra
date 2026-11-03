from segundo_cerebro.rag import montar_prompt
from segundo_cerebro.store import Trecho


def test_prompt_numera_trechos_e_inclui_pergunta():
    trechos = [
        Trecho("Tenho uma cachorra chamada Mel.", {"categoria": "família", "data": "2020"}, 0.1),
        Trecho("Trabalho com dados.", {"categoria": "trabalho"}, 0.3),
    ]
    p = montar_prompt("Qual o nome do meu pet?", trechos)
    assert '<memoria indice="1" categoria="família" data="2020">' in p
    assert '<memoria indice="2" categoria="trabalho">' in p
    assert p.rstrip().endswith("Pergunta: Qual o nome do meu pet?")

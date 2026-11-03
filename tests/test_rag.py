from lembra.rag import montar_prompt
from lembra.supabase import Trecho, _vetor_para_texto


def test_prompt_numera_trechos_e_inclui_pergunta():
    trechos = [
        Trecho("Tenho uma cachorra chamada Mel.", {"categoria": "família", "data": "2020"}, 0.9),
        Trecho("Trabalho com dados.", {"categoria": "trabalho", "data": None}, 0.7),
    ]
    p = montar_prompt("Qual o nome do meu pet?", trechos)
    assert '<memoria indice="1" categoria="família" data="2020">' in p
    assert '<memoria indice="2" categoria="trabalho">' in p
    assert p.rstrip().endswith("Pergunta: Qual o nome do meu pet?")


def test_vetor_vira_texto_no_formato_do_pgvector():
    assert _vetor_para_texto([0.5, -1.0]) == "[0.5000000,-1.0000000]"

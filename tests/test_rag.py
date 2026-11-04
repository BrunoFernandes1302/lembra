from lembra.rag import filtrar_proximos_do_melhor, montar_prompt
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


def test_filtro_mantem_so_trechos_proximos_do_melhor():
    # números reais do teste com o Gemini: certo 0,72; irrelevante 0,59
    t = [Trecho("aluguel", {}, 0.72), Trecho("dentista", {}, 0.59), Trecho("quase", {}, 0.70)]
    assert [x.texto for x in filtrar_proximos_do_melhor(t)] == ["aluguel", "quase"]
    assert filtrar_proximos_do_melhor([]) == []



def test_prompt_traz_a_data_de_hoje_depois_das_memorias():
    from datetime import date
    p = montar_prompt("Quando é a reunião?", [], hoje=date(2026, 11, 4))
    assert "Hoje é quarta-feira, 04/11/2026." in p
    assert p.index("</memorias>") < p.index("Hoje é") < p.index("Pergunta:"), "data no fim: não quebra o cache"

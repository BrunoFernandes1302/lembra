from dataclasses import replace
from datetime import date

import pytest

from lembra import rag
from lembra.config import get_settings
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


# ---------------------------------------------------------------- conversa com memória
HIST = [{"pergunta": "Quanto gastei de mercado em outubro?", "resposta": "Você gastou 1.150 reais de mercado [1]."}]


@pytest.mark.parametrize(("pergunta", "historico", "esperado"), [
    ("e em setembro?", HIST, True),                                   # curta
    ("E quanto foi no mês anterior ao que você falou agora?", HIST, True),  # conectivo + referência
    ("Quanto gastei com a academia no primeiro semestre de 2026?", HIST, False),  # completa: sem custo extra
    ("e em setembro?", [], False),                                    # sem histórico: nada a reescrever
])
def test_so_reescreve_quando_parece_depender(pergunta, historico, esperado):
    assert rag.precisa_reescrever(pergunta, historico) is esperado


class _LLMQueReescreve:
    def __init__(self):
        self.chamadas = []

    def gerar(self, sistema, prompt):
        self.chamadas.append(sistema)
        if sistema == rag.PROMPT_REESCRITA:
            assert "Quanto gastei de mercado em outubro?" in prompt and "e em setembro?" in prompt
            return '"Quanto gastei de mercado em setembro?"'
        return "Resposta gerada."


@pytest.fixture
def ambiente(monkeypatch):
    llm = _LLMQueReescreve()
    buscadas = []
    s = replace(get_settings(), usar_ia=True, modo_agente=False)
    monkeypatch.setattr(rag, "_config_e_vetor", lambda repo, p, settings: (s, [0.1]))
    monkeypatch.setattr(rag, "get_llm", lambda settings: llm)

    def buscar(repo, pergunta, categoria, settings, vetor):
        buscadas.append((pergunta, vetor))
        return [Trecho("Mercado em setembro: 980 reais.", {"data": "30/09/2026"}, 0.8)]

    monkeypatch.setattr(rag, "buscar", buscar)
    return llm, buscadas


def test_pergunta_de_continuacao_e_reescrita_antes_da_busca(ambiente):
    llm, buscadas = ambiente
    r = rag.perguntar(object(), "e em setembro?", historico=HIST)
    assert r.pergunta_entendida == "Quanto gastei de mercado em setembro?", "sem aspas"
    assert buscadas == [("Quanto gastei de mercado em setembro?", None)], "busca com a pergunta completa e vetor refeito"
    assert llm.chamadas.count(rag.PROMPT_REESCRITA) == 1, "uma única chamada extra de reescrita"


def test_sem_historico_nao_gasta_chamada_extra(ambiente):
    llm, buscadas = ambiente
    r = rag.perguntar(object(), "Quanto gastei de mercado em setembro?")
    assert r.pergunta_entendida is None and rag.PROMPT_REESCRITA not in llm.chamadas
    assert buscadas == [("Quanto gastei de mercado em setembro?", [0.1])], "reaproveita o vetor já calculado"


def test_reescrita_que_falha_nao_derruba_a_pergunta(ambiente, monkeypatch):
    llm, buscadas = ambiente

    def quebra(sistema, prompt):
        if sistema == rag.PROMPT_REESCRITA:
            raise RuntimeError("limite da IA")
        return "Resposta gerada."

    monkeypatch.setattr(llm, "gerar", quebra)
    r = rag.perguntar(object(), "e em setembro?", historico=HIST)
    assert r.pergunta_entendida is None and buscadas[0][0] == "e em setembro?"


# ---------------------------------------------------------------- data de hoje sem banco de fusos
def test_data_de_hoje_nao_depende_do_banco_de_fusos_do_sistema():
    """Num servidor sem /usr/share/zoneinfo, ZoneInfo quebra e TODA pergunta falharia. Roda num
    processo à parte com o banco de fusos 'desligado' (PYTHONTZPATH) e exige que a data saia."""
    import os
    import subprocess
    import sys

    codigo = "from lembra.rag import hoje_em_sp, montar_prompt; print(hoje_em_sp().year); " \
             "print('Hoje é' in montar_prompt('oi', []))"
    r = subprocess.run([sys.executable, "-c", codigo], check=False, capture_output=True, text=True,
                       env={**os.environ, "PYTHONTZPATH": "/nao/existe"})
    assert r.returncode == 0, r.stderr[-400:]
    assert r.stdout.split() == [str(date.today().year), "True"]

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
    assert r.stdout.split() == [str(date.today().year), "True"]  # noqa: DTZ011 — o subprocesso usa a mesma data local



# ---------------------------------------------------------------- LLM instável: tentar de novo e explicar
class _ErroHttp(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class _LLMInstavel:
    def __init__(self, falhas):
        self.falhas, self.chamadas = list(falhas), 0

    def gerar(self, sistema, prompt):
        self.chamadas += 1
        if self.falhas:
            raise self.falhas.pop(0)
        return "Resposta."


def test_sobrecarga_temporaria_passa_na_segunda_tentativa():
    llm = _LLMInstavel([_ErroHttp(503)])
    esperas = []
    assert rag.gerar_com_novas_tentativas(llm, "s", "p", dormir=esperas.append) == "Resposta."
    assert llm.chamadas == 2 and esperas == [1.0]


def test_desiste_depois_de_tres_tentativas():
    llm = _LLMInstavel([_ErroHttp(503)] * 5)
    with pytest.raises(_ErroHttp):
        rag.gerar_com_novas_tentativas(llm, "s", "p", dormir=lambda s: None)
    assert llm.chamadas == 3


def test_erro_que_nao_e_temporario_nao_e_repetido():
    llm = _LLMInstavel([_ErroHttp(404)])  # modelo aposentado / chave inválida: repetir não adianta
    with pytest.raises(_ErroHttp):
        rag.gerar_com_novas_tentativas(llm, "s", "p", dormir=lambda s: None)
    assert llm.chamadas == 1


@pytest.mark.parametrize(("erro", "trecho"), [
    (_ErroHttp(429), "limite de uso"),
    (_ErroHttp(503), "sobrecarregado"),
    (_ErroHttp(404), "erro 404"),
    (KeyError("x"), "KeyError"),
])
def test_motivo_da_falha_explica_sem_vazar_o_texto_do_erro(erro, trecho):
    frase = rag.motivo_da_falha(erro)
    assert trecho in frase and "HTTP" not in frase


def test_orcamento_de_tempo_interrompe_o_retry():
    llm = _LLMInstavel([_ErroHttp(503)] * 5)
    horas = iter([0.0, 11.5])  # a 2ª leitura já está perto do limite: a próxima espera estouraria
    with pytest.raises(_ErroHttp):
        rag.gerar_com_novas_tentativas(llm, "s", "p", dormir=lambda s: None, relogio=lambda: next(horas))
    assert llm.chamadas == 1


# ---------------------------------------------------------------- modelo aposentado (404): cai no padrão
class _ClienteGemini:
    def __init__(self, aposentados):
        self.aposentados, self.chamados = set(aposentados), []
        self.models = self

    def generate_content(self, model, **kw):
        self.chamados.append(model)
        if model in self.aposentados:
            raise _ErroHttp(404)
        return "ok"


def test_modelo_aposentado_cai_no_padrao_e_lembra():
    from lembra.llm import MODELO_PADRAO_GEMINI, gerar_conteudo_gemini

    c = _ClienteGemini({"gemini-antigo"})
    resposta, usado = gerar_conteudo_gemini(c, "gemini-antigo", contents="x")
    assert resposta == "ok" and usado == MODELO_PADRAO_GEMINI
    assert c.chamados == ["gemini-antigo", MODELO_PADRAO_GEMINI]


def test_404_do_proprio_padrao_e_outros_erros_nao_sao_mascarados():
    from lembra.llm import MODELO_PADRAO_GEMINI, gerar_conteudo_gemini

    with pytest.raises(_ErroHttp):  # o padrão também sumiu: não há para onde cair
        gerar_conteudo_gemini(_ClienteGemini({MODELO_PADRAO_GEMINI}), MODELO_PADRAO_GEMINI, contents="x")

    class Sobrecarga(_ClienteGemini):
        def generate_content(self, model, **kw):
            raise _ErroHttp(503)

    with pytest.raises(_ErroHttp):  # 503 segue para o retry, não vira troca de modelo
        gerar_conteudo_gemini(Sobrecarga([]), "gemini-antigo", contents="x")

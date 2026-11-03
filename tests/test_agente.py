"""Testes do modo agente com um MOTOR FALSO: ele finge ser o LLM e pede ferramentas num roteiro
conhecido. Testa o ciclo (pedir → executar → devolver → responder) sem gastar cota."""

from dataclasses import replace

import pytest

from lembra.agente import MAX_PASSOS, Chamada, Ferramentas, calcular_seguro, executar_agente
from lembra.config import get_settings
from lembra.supabase import Trecho


class RepoSimples:
    def __init__(self):
        self.memorias = [
            {"id": "a", "texto": "Pago 1.800 de aluguel e 450 de condomínio.", "categoria": "finanças", "data_evento": ""},
            {"id": "b", "texto": "Academia custa 120 por mês.", "categoria": "saúde", "data_evento": ""},
        ]

    def buscar(self, vetor, k, categoria=None, modelo=None):
        return [Trecho(m["texto"], {"memoria_id": m["id"], "categoria": m["categoria"], "data": ""}, 0.7)
                for m in self.memorias if categoria is None or m["categoria"] == categoria][:k]

    def listar_memorias(self, categoria=None, limite=200):
        return [m for m in self.memorias if categoria is None or m["categoria"] == categoria]

    def listar_categorias(self):
        return [{"nome": "finanças", "memorias": 1}, {"nome": "saúde", "memorias": 1}]

    def obter_config(self):
        return None


class EmbedderNulo:
    def embed_query(self, t):
        return [0.0]


class MotorRoteiro:
    """Pede as ferramentas do roteiro, uma rodada por vez; depois responde."""

    def __init__(self, rodadas, final="Resposta final [1]"):
        self.rodadas, self.final, self.devolvidos = list(rodadas), final, []

    def proximo(self):
        if self.rodadas:
            return None, self.rodadas.pop(0)
        return self.final, []

    def devolver(self, resultados):
        self.devolvidos.append(resultados)

    def finalizar(self):
        return "resposta forçada"


@pytest.fixture
def s(monkeypatch):
    from lembra import rag

    monkeypatch.setattr(rag, "embedder_de", lambda _: EmbedderNulo())
    return replace(get_settings(), llm_provider="gemini", modo_agente=True)


def test_ciclo_busca_calcula_e_responde(s):
    motor = MotorRoteiro([
        [Chamada("buscar_memorias", {"consulta": "moradia"}), Chamada("buscar_memorias", {"consulta": "academia"})],
        [Chamada("calcular", {"expressao": "1800 + 450 + 120"})],
    ])
    texto, fontes, passos = executar_agente(RepoSimples(), "quanto gasto por mês?", None, s, motor)
    assert texto == "Resposta final [1]"
    assert [p["ferramenta"] for p in passos] == ["buscar_memorias", "buscar_memorias", "calcular"]
    assert passos[2]["resumo"] == "= 2370"
    assert len(fontes) == 2, "trechos repetidos nas duas buscas recebem o MESMO número"
    assert motor.devolvidos[1][0][1]["resultado"] == 2370


def test_limite_de_passos(s):
    infinito = [[Chamada("data_de_hoje", {})] for _ in range(MAX_PASSOS + 3)]
    texto, _, passos = executar_agente(RepoSimples(), "?", None, s, MotorRoteiro(infinito))
    assert texto == "resposta forçada" and len(passos) == MAX_PASSOS


def test_ferramenta_desconhecida_ou_com_erro_nao_derruba(s):
    f = Ferramentas(RepoSimples(), s)
    assert "erro" in f.executar("apagar_tudo", {})
    assert "erro" in f.executar("calcular", {"expressao": "__import__('os')"})
    assert "erro" in f.executar("buscar_memorias", {})  # argumento obrigatório faltando


def test_filtros_da_categoria_padrao(s):
    f = Ferramentas(RepoSimples(), s, categoria_padrao="saúde")
    assert f.listar_memorias()["total"] == 1
    assert f.listar_memorias(texto_contem="ALUGUEL", categoria="finanças")["total"] == 1


@pytest.mark.parametrize("expr,esperado", [("1800 + 450", 2250), ("(10 - 4) * 2,5", 15), ("-3 + 5", 2), ("120 x 12", 1440)])
def test_calculadora(expr, esperado):
    assert calcular_seguro(expr) == esperado


@pytest.mark.parametrize("ataque", ["__import__('os').system('rm -rf /')", "open('/etc/passwd')", "2 ** 999999999",
                                     "[1,2,3]", "x.y", "a"])
def test_calculadora_recusa_codigo(ataque):
    with pytest.raises((ValueError, SyntaxError)):
        calcular_seguro(ataque)


def test_dias_ate_conta_em_codigo(s):
    from datetime import date

    f = Ferramentas(RepoSimples(), s)
    # o caso que o agente errou "de cabeça" (disse 352): de 03/11/2026 até 21/08 = 291 dias
    r = f.dias_ate(21, 8, hoje=date(2026, 11, 3))
    assert r["dias"] == 291 and r["data"] == "21/08/2027"
    assert f.dias_ate(25, 12, 2026, hoje=date(2026, 11, 3))["dias"] == 52
    assert f.dias_ate(1, 1, 2026, hoje=date(2026, 11, 3))["sentido"] == "passaram"

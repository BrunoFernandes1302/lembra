"""Testes do avaliador (avaliacao/avaliar.py), sem chamar a API."""

import sys
from pathlib import Path

from google.genai.errors import ServerError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "avaliacao"))
from avaliar import erro_da_api


def test_falha_da_api_permite_salvar_parcial():
    assert erro_da_api(ServerError(503, {"error": {"code": 503, "message": "high demand", "status": "UNAVAILABLE"}}))
    assert erro_da_api(ConnectionResetError("rede caiu"))


def test_erro_de_programacao_nao_vira_parcial():
    assert not erro_da_api(KeyError("campo_novo"))
    assert not erro_da_api(TypeError("assinatura mudou"))

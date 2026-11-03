"""Testes do chunking."""

import itertools

import pytest

from lembra.chunking import chunk_text

PARAGRAFOS = (
    "Nasci em Belo Horizonte em 1995. Minha infância foi no bairro Santa Tereza.\n\n"
    "Comecei a trabalhar com tecnologia em 2016, como estagiário de suporte.\n\n"
    "Tenho uma cachorra chamada Mel, uma vira-lata caramelo adotada em 2020."
)


# Regra 1
def test_texto_vazio_retorna_lista_vazia():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


# Regra 2
def test_texto_curto_vira_um_chunk():
    assert chunk_text("  Olá, mundo.  ", chunk_size=100, overlap=0) == ["Olá, mundo."]


# Regra 3
@pytest.mark.parametrize("chunk_size", [20, 50, 80, 120])
def test_nenhum_chunk_passa_do_limite(chunk_size):
    chunks = chunk_text(PARAGRAFOS * 3, chunk_size=chunk_size, overlap=10)
    assert chunks, "deveria gerar chunks"
    assert all(len(c) <= chunk_size for c in chunks)


# Regra 4
def test_prefere_quebrar_por_paragrafo():
    chunks = chunk_text(PARAGRAFOS, chunk_size=90, overlap=0)
    assert chunks[0].startswith("Nasci em Belo Horizonte")
    assert chunks[0].endswith("Santa Tereza.")
    assert any(c.startswith("Tenho uma cachorra") for c in chunks)


def test_nao_corta_palavras_quando_ha_espaco():
    texto = "palavra " * 50
    for c in chunk_text(texto, chunk_size=30, overlap=0):
        assert all(p == "palavra" for p in c.split())


# Regra 5
def test_chunks_vizinhos_tem_sobreposicao():
    texto = " ".join(f"frase{i}." for i in range(60))
    chunks = chunk_text(texto, chunk_size=60, overlap=20)
    assert len(chunks) > 2
    for anterior, proximo in itertools.pairwise(chunks):
        ultima_palavra = anterior.split()[-1]
        assert ultima_palavra in proximo, "o final de um chunk deveria reaparecer no próximo"


def test_nada_se_perde():
    chunks = chunk_text(PARAGRAFOS, chunk_size=50, overlap=10)
    juntos = " ".join(chunks)
    for palavra in PARAGRAFOS.split():
        assert palavra in juntos


# Regra 6
@pytest.mark.parametrize("chunk_size,overlap", [(0, 0), (-5, 0), (100, 100), (100, -1)])
def test_parametros_invalidos(chunk_size, overlap):
    with pytest.raises(ValueError):
        chunk_text("qualquer coisa", chunk_size=chunk_size, overlap=overlap)

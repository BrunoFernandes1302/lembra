"""AULA 1 — Chunking: quebrar textos longos em pedaços menores ("chunks").

Leia antes: docs/aulas/01-chunking.md

Sua missão: implementar `chunk_text` até todos os testes passarem:

    pytest tests/test_chunking.py -v

Dica: comece fazendo passar só o primeiro teste. Depois o segundo. Um de cada vez.
"""

from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    """Divide `text` em chunks de até `chunk_size` caracteres.

    Regras (cada uma tem um teste correspondente):
      1. Texto vazio (ou só espaços) -> lista vazia.
      2. Texto que cabe em um chunk -> lista com 1 item (o texto, sem espaços nas pontas).
      3. Nenhum chunk pode passar de `chunk_size` caracteres.
      4. Preferir quebrar em parágrafo ("\\n\\n"); se não der, linha ("\\n"),
         depois frase (". "), depois palavra (" "). Só cortar palavra no meio em último caso.
      5. Chunks vizinhos compartilham um trecho de até `overlap` caracteres
         (o final de um aparece no começo do próximo).
      6. `chunk_size <= 0` ou `overlap` fora de [0, chunk_size) -> ValueError.
    """
    # TODO: implemente aqui. Apague o raise quando começar.
    raise NotImplementedError("Aula 1: implemente chunk_text")

"""Linha de comando:  lembra adicionar | perguntar | buscar | reindexar | status"""

from __future__ import annotations

import argparse
import sys

from . import memorias, rag
from .config import get_settings
from .store import VectorStore


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="lembra", description="Lembra — seu assistente de vida pessoal")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("adicionar", help="adiciona uma memória (texto ou stdin)")
    a.add_argument("texto", nargs="?", help="texto da memória; omita para ler do stdin")
    a.add_argument("-c", "--categoria", default="geral")
    a.add_argument("-d", "--data", default="", help='quando aconteceu, ex.: "2020"')

    q = sub.add_parser("perguntar", help="pergunta algo ao Lembra")
    q.add_argument("pergunta")

    b = sub.add_parser("buscar", help="mostra só os trechos recuperados (sem LLM)")
    b.add_argument("pergunta")

    sub.add_parser("reindexar", help="reconstrói o índice a partir de memorias.jsonl")
    sub.add_parser("status", help="mostra quantas memórias e chunks existem")

    args = p.parse_args(argv)

    if args.cmd == "adicionar":
        texto = args.texto or sys.stdin.read()
        n = memorias.salvar(memorias.Memoria(texto=texto, categoria=args.categoria, data=args.data))
        print(f"Memória salva em {n} chunk(s).")
    elif args.cmd == "perguntar":
        r = rag.perguntar(args.pergunta)
        print(r.texto)
        _imprimir_fontes(r.fontes)
    elif args.cmd == "buscar":
        _imprimir_fontes(rag.buscar(args.pergunta), completo=True)
    elif args.cmd == "reindexar":
        print(f"Índice reconstruído: {memorias.reindexar()} chunk(s).")
    elif args.cmd == "status":
        s = get_settings()
        print(f"Memórias: {len(memorias.listar(s))} | Chunks no índice: {VectorStore(s.chroma_dir).total()}")


def _imprimir_fontes(trechos, completo: bool = False) -> None:
    if not trechos:
        return
    print("\nFontes:")
    for i, t in enumerate(trechos, start=1):
        texto = t.texto if completo else t.texto[:100] + ("…" if len(t.texto) > 100 else "")
        print(f"  [{i}] similaridade={t.similaridade:.2f} | {t.metadados.get('categoria')} | {texto}")


if __name__ == "__main__":
    main()

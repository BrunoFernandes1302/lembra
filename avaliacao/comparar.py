"""Compara as rodadas salvas em avaliacao/resultados/ lado a lado.

Uso:  python avaliacao/comparar.py            (todas as rodadas)
      python avaliacao/comparar.py chunk800 chunk250   (só as rodadas com esses rótulos)
"""

import json
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent / "resultados"
METRICAS = ["recall@K", "acerto@1", "MRR", "correta", "fiel", "abstencao_correta"]


def main():
    rodadas = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(PASTA.glob("*.json"))]
    if len(sys.argv) > 1:
        rodadas = [r for r in rodadas if r["rotulo"] in sys.argv[1:]]
    if not rodadas:
        sys.exit("Nenhuma rodada encontrada. Rode avaliacao/avaliar.py antes.")
    larg = max(12, *(len(r["rotulo"]) for r in rodadas))
    print(f"{'métrica':<20}" + "".join(f"{r['rotulo']:>{larg + 2}}" for r in rodadas))
    for campo in ("chunk_size", "chunk_overlap", "top_k", "chunks_indexados", "prompt", "repeticoes"):
        print(f"{campo:<20}" + "".join(f"{str(r['config'].get(campo, '—')):>{larg + 2}}" for r in rodadas))
    print("-" * (20 + (larg + 2) * len(rodadas)))
    for m in METRICAS:
        vals = [r["resumo"].get(m) for r in rodadas]
        fmt = (lambda v: f"{v:.2f}") if m == "MRR" else (lambda v: f"{v:.0%}")
        print(f"{m:<20}" + "".join(f"{(fmt(v) if v is not None else '—'):>{larg + 2}}" for v in vals))


if __name__ == "__main__":
    main()

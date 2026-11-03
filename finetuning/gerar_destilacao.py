"""LoRA, etapa A: dados de DESTILAÇÃO (professor grande -> aluno pequeno).

Para cada pergunta sintética, montamos EXATAMENTE o prompt que o Lembra usa (regras + 5 memórias
mais parecidas) e o Gemini (professor) responde. A resposta vira o "gabarito" do aluno.

Exemplos NEGATIVOS (~25%): tiramos de propósito a memória certa do contexto; o gabarito vira
"não encontrei". Sem isso, um modelo pequeno aprende a sempre responder algo — e inventa.

Uso:  python finetuning/gerar_destilacao.py   -> finetuning/dados/destilacao.jsonl
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))

from pydantic import BaseModel  # noqa: E402

from avaliar import com_novas_tentativas  # noqa: E402
from lembra import rag  # noqa: E402
from lembra.config import get_settings  # noqa: E402
from lembra.supabase import Trecho  # noqa: E402

PASTA = Path(__file__).resolve().parent / "dados"
N_EXEMPLOS = 120
FRACAO_NEGATIVOS = 0.25


def vetores(textos, tipo):
    cache = json.loads((PASTA / "cache_embeddings.json").read_text())
    return np.array([cache[hashlib.sha1(f"{tipo}|{t}".encode()).hexdigest()] for t in textos], dtype=np.float32)


class Respostas(BaseModel):
    respostas: list[str]


def main():
    from google import genai
    from google.genai import types

    random.seed(7)
    s = get_settings()
    memorias = json.loads((RAIZ / "avaliacao/conjunto_dificil.json").read_text(encoding="utf-8"))["memorias"]
    D = vetores([m["texto"] for m in memorias], "doc")
    sint = json.loads((PASTA / "perguntas_sinteticas.json").read_text(encoding="utf-8"))
    pares = [(q, mid) for mid, qs in sint.items() for q in qs]
    random.shuffle(pares)
    pares = pares[:N_EXEMPLOS]
    Q = vetores([p[0] for p in pares], "query")

    exemplos = []
    for (pergunta, mid), q in zip(pares, Q):
        ordem = list(np.argsort(-(D @ q)))
        negativo = random.random() < FRACAO_NEGATIVOS
        if negativo:  # tira a memória certa: a resposta correta passa a ser "não encontrei"
            ordem = [i for i in ordem if memorias[i]["id"] != mid]
        trechos = [Trecho(memorias[i]["texto"], {"categoria": memorias[i]["categoria"],
                                                 "data": memorias[i]["data_evento"]}, float(D[i] @ q))
                   for i in ordem[:5]]
        exemplos.append({"pergunta": pergunta, "negativo": negativo,
                         "prompt": rag.montar_prompt(pergunta, trechos)})

    cliente = genai.Client(api_key=s.gemini_api_key)
    instr = (rag.SYSTEM_PROMPT + "\n\nVocê vai receber VÁRIOS casos numerados, cada um com suas memórias e "
             "pergunta. Responda cada caso de forma independente, seguindo as regras, e devolva as respostas "
             "na mesma ordem, uma por caso.")
    for i in range(0, len(exemplos), 8):
        lote = exemplos[i : i + 8]
        conteudo = "\n\n".join(f"=== CASO {j + 1} ===\n{e['prompt']}" for j, e in enumerate(lote))

        def pedir():
            r = cliente.models.generate_content(
                model=s.gemini_model, contents=conteudo,
                config=types.GenerateContentConfig(system_instruction=instr, temperature=0.2,
                                                   response_mime_type="application/json", response_schema=Respostas))
            out = r.parsed if isinstance(r.parsed, Respostas) else Respostas.model_validate_json(r.text)
            if len(out.respostas) != len(lote):
                raise RuntimeError("503 quantidade de respostas diferente; tentando de novo")
            return out

        for e, resp in zip(lote, com_novas_tentativas(pedir).respostas):
            e["resposta"] = resp.strip()
        print(f"{min(i + 8, len(exemplos))}/{len(exemplos)} exemplos", flush=True)

    with open(PASTA / "destilacao.jsonl", "w", encoding="utf-8") as f:
        for e in exemplos:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    neg = [e for e in exemplos if e["negativo"]]
    admitiu = sum("não encontrei" in e["resposta"].lower() for e in neg)
    print(f"Salvo: {len(exemplos)} exemplos ({len(neg)} negativos; o professor admitiu não saber em {admitiu}).")


if __name__ == "__main__":
    main()

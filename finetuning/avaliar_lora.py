"""LoRA, etapa C: a prova. O mesmo modelo pequeno, SEM e COM o adaptador LoRA, responde às
perguntas do conjunto difícil (que o treino nunca viu), com as mesmas memórias; o mesmo juiz
(Gemini) avalia as duas versões.

Uso:  python finetuning/avaliar_lora.py   -> finetuning/dados/resultado_lora.json
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))

from avaliar import com_novas_tentativas, julgar

from lembra import rag
from lembra.config import get_settings
from lembra.supabase import Trecho

PASTA = Path(__file__).resolve().parent
MODELO = "Qwen/Qwen2.5-0.5B-Instruct"


def vetores(textos, tipo):
    cache = json.loads((PASTA / "dados" / "cache_embeddings.json").read_text())
    return np.array([cache[hashlib.sha1(f"{tipo}|{t}".encode()).hexdigest()] for t in textos], dtype=np.float32)


def responder(modelo, tok, prompt):
    msgs = [{"role": "system", "content": rag.SYSTEM_PROMPT}, {"role": "user", "content": prompt}]
    texto = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    ids = tok(texto, return_tensors="pt", add_special_tokens=False)
    with torch.no_grad():
        out = modelo.generate(**ids, max_new_tokens=160, do_sample=False)
    return tok.decode(out[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()


def main():
    from google import genai
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    s = get_settings()
    juiz = genai.Client(api_key=s.gemini_api_key)
    conj = json.loads((RAIZ / "avaliacao/conjunto_dificil.json").read_text(encoding="utf-8"))
    mem, perg = conj["memorias"], conj["perguntas"]
    D = vetores([m["texto"] for m in mem], "doc")
    Q = vetores([p["pergunta"] for p in perg], "query")
    casos = []
    for p, q in zip(perg, Q):
        top = np.argsort(-(D @ q))[:5]
        trechos = [Trecho(mem[i]["texto"], {"categoria": mem[i]["categoria"], "data": mem[i]["data_evento"]},
                          float(D[i] @ q)) for i in top]
        casos.append({**p, "trechos": trechos, "prompt": rag.montar_prompt(p["pergunta"], trechos)})

    tok = AutoTokenizer.from_pretrained(MODELO)
    base = AutoModelForCausalLM.from_pretrained(MODELO, dtype=torch.float32)
    base.eval()
    resultados = {"sem_lora": [], "com_lora": []}
    for nome in ("sem_lora", "com_lora"):
        modelo = base if nome == "sem_lora" else PeftModel.from_pretrained(base, PASTA / "modelos" / "lora-lembra")
        for c in casos:
            t = time.time()
            resp = responder(modelo, tok, c["prompt"])
            seg = time.time() - t
            v = com_novas_tentativas(julgar, juiz, "gemini-flash-lite-latest", c["pergunta"], c["esperada"],
                                     c["trechos"], resp)
            time.sleep(2)
            resultados[nome].append({"id": c["id"], "tipo": c["tipo"], "resposta": resp, "correta": v.correta,
                                     "fiel": v.fiel, "justificativa": v.justificativa, "segundos": round(seg, 1)})
            print(f"[{nome}] {c['id']} correta={'✓' if v.correta else '✗'} fiel={'✓' if v.fiel else '✗'} "
                  f"({seg:.0f}s) {resp[:110]!r}", flush=True)

    def taxa(lista, campo, filtro=lambda r: True):
        sel = [r for r in lista if filtro(r)]
        return sum(r[campo] for r in sel) / len(sel) if sel else 0

    print(f"\n{'métrica':<22}{'sem LoRA':>10}{'com LoRA':>10}")
    for rot, campo, f in [("correta", "correta", lambda r: True), ("fiel (não inventou)", "fiel", lambda r: True),
                          ("admitiu não saber", "correta", lambda r: r["tipo"] == "sem_resposta")]:
        print(f"{rot:<22}{taxa(resultados['sem_lora'], campo, f):>10.0%}{taxa(resultados['com_lora'], campo, f):>10.0%}")
    (PASTA / "dados" / "resultado_lora.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=2),
                                                        encoding="utf-8")


if __name__ == "__main__":
    main()

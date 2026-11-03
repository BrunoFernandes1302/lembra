"""LoRA, etapa B: ensinar um LLM PEQUENO e aberto a responder como o Lembra.

- Aluno: Qwen2.5-0.5B-Instruct (500 milhões de parâmetros; roda num computador comum / Ollama).
- LoRA: o modelo fica CONGELADO; acoplamos matrizes pequenas ("de baixo posto", r=8) nas camadas
  de atenção e treinamos só elas (<1% dos parâmetros). Resultado: um "adaptador" de poucos MB.
- Prompt MASCARADO: o erro é calculado só sobre a RESPOSTA (rótulo -100 no prompt), para o modelo
  aprender a responder, e não a repetir as regras e as memórias.
- Laço de treino escrito à mão (sem o Trainer pronto) para ficar visível.

Roda em CPU (devagar) ou GPU (Colab). Uso:
    python finetuning/treinar_lora.py         -> finetuning/modelos/lora-lembra/
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import torch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from lembra.rag import SYSTEM_PROMPT  # noqa: E402

MODELO = "Qwen/Qwen2.5-0.5B-Instruct"
PASTA = Path(__file__).resolve().parent
SAIDA = PASTA / "modelos" / "lora-lembra"
EPOCAS = 2
LR = 2e-4
ACUMULAR = 4        # "lote virtual" de 4 exemplos (acumula gradientes antes de ajustar)
MAX_TOKENS = 1024


def preparar(tok, ex):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": ex["prompt"]}]
    # gera o TEXTO no formato de chat do modelo e só depois converte em números (à prova de versão)
    texto_prompt = tok.apply_chat_template(msgs, add_generation_prompt=True, tokenize=False)
    prompt_ids = tok(texto_prompt, add_special_tokens=False)["input_ids"]
    resp_ids = tok(ex["resposta"] + tok.eos_token, add_special_tokens=False)["input_ids"]
    ids = (list(prompt_ids) + resp_ids)[:MAX_TOKENS]
    rotulos = ([-100] * len(prompt_ids) + resp_ids)[:MAX_TOKENS]  # -100 = não conta no erro (máscara)
    return torch.tensor([ids]), torch.tensor([rotulos])


def main():
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.manual_seed(0)
    random.seed(0)
    tok = AutoTokenizer.from_pretrained(MODELO)
    modelo = AutoModelForCausalLM.from_pretrained(MODELO, dtype=torch.float32)
    total = sum(p.numel() for p in modelo.parameters())

    cfg = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    modelo = get_peft_model(modelo, cfg)  # congela o modelo e acopla as matrizes LoRA
    treinaveis = sum(p.numel() for p in modelo.parameters() if p.requires_grad)
    print(f"Parâmetros: {total / 1e6:.0f} M no modelo | treináveis (LoRA): {treinaveis / 1e6:.2f} M "
          f"({treinaveis / total:.2%})", flush=True)

    dados = [json.loads(l) for l in open(PASTA / "dados" / "destilacao.jsonl", encoding="utf-8")]
    exemplos = [preparar(tok, e) for e in dados]
    opt = torch.optim.AdamW([p for p in modelo.parameters() if p.requires_grad], lr=LR)
    modelo.train()
    passo, inicio = 0, time.time()
    for ep in range(1, EPOCAS + 1):
        random.shuffle(exemplos)
        soma = 0.0
        for i, (ids, rot) in enumerate(exemplos, 1):
            perda = modelo(input_ids=ids, labels=rot).loss / ACUMULAR
            perda.backward()  # retropropagação: calcula como cada peso LoRA influenciou o erro
            soma += perda.item() * ACUMULAR
            if i % ACUMULAR == 0 or i == len(exemplos):
                opt.step()     # ajusta só os pesos LoRA
                opt.zero_grad()
                passo += 1
            if i % 20 == 0:
                print(f"época {ep} | exemplo {i:3d}/{len(exemplos)} | perda média {soma / i:.3f} | "
                      f"{(time.time() - inicio) / 60:.1f} min", flush=True)
        print(f"== fim da época {ep}: perda média {soma / len(exemplos):.3f}", flush=True)

    SAIDA.mkdir(parents=True, exist_ok=True)
    modelo.save_pretrained(SAIDA)  # salva SÓ o adaptador LoRA (poucos MB), não o modelo inteiro
    tamanho = sum(f.stat().st_size for f in SAIDA.rglob("*") if f.is_file()) / 1e6
    print(f"Adaptador salvo em {SAIDA.relative_to(RAIZ)} ({tamanho:.1f} MB). "
          f"Tempo total: {(time.time() - inicio) / 60:.1f} min")


if __name__ == "__main__":
    main()

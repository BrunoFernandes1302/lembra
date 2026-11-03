# Fine-tuning no Lembra

Dois experimentos de "treinar só a ponta". Os conceitos e as lições estão em
[`docs/conceitos.md`](../docs/conceitos.md), seção 13.

```bash
pip install -e ".[finetuning]"   # numpy, torch, transformers, peft (NÃO vão para a Vercel)
export GEMINI_API_KEY=...        # usado para dados sintéticos, embeddings e o juiz
```

## 1. Adaptador de embeddings (busca)

O modelo base (embeddings do Gemini) fica **congelado**; treina-se uma matriz 768 × 768 que ajusta
o vetor da pergunta antes da busca.

| Ordem | Script | O que faz |
|-------|--------|-----------|
| 1 | `gerar_dados.py` | O Gemini inventa ~6 perguntas por memória → `dados/perguntas_sinteticas.json` |
| 2 | `treinar_adaptador.py` | Treina a matriz (InfoNCE, validação, early stopping) e compara sem × com adaptador nas perguntas escritas à mão |

Leva poucos minutos no processador.

## 2. LoRA num LLM pequeno (geração)

Ensina o **Qwen2.5-0.5B-Instruct** (aberto, roda em computador comum / Ollama) a responder como o
Lembra, por **destilação** do Gemini.

| Ordem | Script | O que faz |
|-------|--------|-----------|
| 1 | `gerar_dados.py` | (se ainda não rodou) perguntas sintéticas |
| 2 | `gerar_destilacao.py` | O Gemini (professor) responde 120 casos no formato do Lembra; ~25% negativos ("não encontrei") → `dados/destilacao.jsonl` |
| 3 | `treinar_lora.py` | LoRA r=8 na atenção (0,22% dos parâmetros), prompt mascarado → `modelos/lora-lembra/` |
| 4 | `avaliar_lora.py` | Mesmo modelo sem × com LoRA no conjunto difícil, avaliado pelo juiz |

No processador (4 núcleos), o treino leva ~20 minutos. Com GPU (ex.: Google Colab grátis, T4), alguns minutos.

## Arquivos gerados

- `dados/perguntas_sinteticas.json`, `dados/destilacao.jsonl`, `dados/resultado_*.json`: versionados (pequenos).
- `dados/cache_embeddings.json`, `dados/*.npy`, `modelos/`: **não** versionados (grandes e regeneráveis).

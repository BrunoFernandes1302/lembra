"""Fine-tuning, etapa 2: treinar SÓ A PONTA da busca (um "adaptador de embeddings").

- Modelo base CONGELADO: os embeddings do Gemini (não podemos nem queremos mexer neles).
- Ponta treinável: uma matriz W (768 x 768) aplicada ao vetor da PERGUNTA antes da busca:
      q' = normaliza(q · W)
  W começa como identidade ("não muda nada") e aprende a aproximar perguntas das memórias certas.
- Perda contrastiva (InfoNCE): para cada pergunta, a memória certa deve ganhar de TODAS as outras.
- Regularização: penaliza W se afastar da identidade (poucos dados -> risco de distorcer demais).
- Validação: 20% das perguntas sintéticas ficam fora do treino para detectar sobreajuste;
  guardamos a época com MENOR PERDA de validação (early stopping). Lição da 1ª tentativa: o
  acerto@1 da validação já era 100% antes do treino (efeito teto) e o "melhor" ficou sendo a
  matriz inicial. A perda mede COM QUANTA FOLGA a memória certa vence: é uma régua mais fina.
- Prova final: perguntas escritas à mão (avaliacao/conjunto_dificil.json), que o treino nunca viu.

Uso:  python finetuning/treinar_adaptador.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))

from avaliar import com_novas_tentativas  # noqa: E402
from lembra.config import embedder_de, get_settings  # noqa: E402

PASTA = Path(__file__).resolve().parent / "dados"
SEMENTE = 42
TAU = 0.05          # "temperatura" da perda: menor = mais exigente com a margem de vitória
LAMBDA_REG = 0.5    # força do freio que mantém W perto da identidade
EPOCAS = 150
LR = 1e-3


# ---------------------------------------------------------------- embeddings com cache
def _chave(tipo, texto):
    return hashlib.sha1(f"{tipo}|{texto}".encode()).hexdigest()


def embeddings(textos: list[str], tipo: str) -> np.ndarray:
    """Vetores do Gemini, com cache em disco (não pagar duas vezes pelo mesmo texto)."""
    arq = PASTA / "cache_embeddings.json"
    cache = json.loads(arq.read_text()) if arq.exists() else {}
    faltam = [t for t in textos if _chave(tipo, t) not in cache]
    if faltam:
        emb = embedder_de(get_settings())
        f = emb.embed_documents if tipo == "doc" else lambda ts: [emb.embed_query(x) for x in ts]
        for i in range(0, len(faltam), 50):
            lote = faltam[i : i + 50]
            for t, v in zip(lote, com_novas_tentativas(f, lote)):
                cache[_chave(tipo, t)] = v
        arq.write_text(json.dumps(cache))
    return np.array([cache[_chave(tipo, t)] for t in textos], dtype=np.float32)


# ---------------------------------------------------------------- métricas de busca
def medir(Q: np.ndarray, D: np.ndarray, relevantes: list[list[int]], W: np.ndarray | None = None) -> dict:
    if W is not None:
        Q = Q @ W
        Q = Q / np.linalg.norm(Q, axis=1, keepdims=True)
    ordem = np.argsort(-(Q @ D.T), axis=1)
    r3, r5, a1, rr = [], [], [], []
    for linha, rel in zip(ordem, relevantes):
        rel = set(rel)
        r3.append(len(rel & set(linha[:3])) / len(rel))
        r5.append(len(rel & set(linha[:5])) / len(rel))
        a1.append(float(linha[0] in rel))
        pos = next(i for i, d in enumerate(linha, 1) if d in rel)
        rr.append(1 / pos)
    return {"recall@3": np.mean(r3), "recall@5": np.mean(r5), "acerto@1": np.mean(a1), "MRR": np.mean(rr)}


# ---------------------------------------------------------------- treino
def treinar(Qtr, ytr, Qva, yva, D):
    torch.manual_seed(SEMENTE)
    Dt = torch.tensor(D)
    Qtr_t, Qva_t = torch.tensor(Qtr), torch.tensor(Qva)
    ytr_t = torch.tensor(ytr)
    I = torch.eye(D.shape[1])
    W = torch.nn.Parameter(I.clone())  # começa como identidade: no início, igual à busca atual
    opt = torch.optim.Adam([W], lr=LR)

    yva_t = torch.tensor(yva)

    def acerto(Q, y, Wm):
        q = torch.nn.functional.normalize(Q @ Wm, dim=1)
        return (torch.argmax(q @ Dt.T, dim=1) == torch.tensor(y)).float().mean().item()

    def perda_val(Wm):
        q = torch.nn.functional.normalize(Qva_t @ Wm, dim=1)
        return torch.nn.functional.cross_entropy((q @ Dt.T) / TAU, yva_t).item()

    melhor = (perda_val(I), 0, I.clone())
    print(f"época   0 | perda treino   —   | perda validação {melhor[0]:.3f} | acerto@1 treino {acerto(Qtr_t, ytr, I):.0%} | validação {acerto(Qva_t, yva, I):.0%}")
    for ep in range(1, EPOCAS + 1):
        q = torch.nn.functional.normalize(Qtr_t @ W, dim=1)
        logits = (q @ Dt.T) / TAU
        perda = torch.nn.functional.cross_entropy(logits, ytr_t) + LAMBDA_REG * ((W - I) ** 2).sum()
        opt.zero_grad()
        perda.backward()
        opt.step()
        with torch.no_grad():
            pv = perda_val(W)
            if pv < melhor[0]:
                melhor = (pv, ep, W.detach().clone())
            if ep % 25 == 0:
                print(f"época {ep:3d} | perda treino {perda.item():.3f} | perda validação {pv:.3f} | "
                      f"acerto@1 treino {acerto(Qtr_t, ytr, W):.0%} | validação {acerto(Qva_t, yva, W):.0%}")
    print(f"→ menor perda de validação na época {melhor[1]} ({melhor[0]:.3f}); essa é a matriz guardada (early stopping)")
    return melhor[2].numpy()


def main():
    random.seed(SEMENTE)
    conjunto = json.loads((RAIZ / "avaliacao/conjunto_dificil.json").read_text(encoding="utf-8"))
    memorias = conjunto["memorias"]
    ids = [m["id"] for m in memorias]
    D = embeddings([m["texto"] for m in memorias], "doc")

    sint = json.loads((PASTA / "perguntas_sinteticas.json").read_text(encoding="utf-8"))
    pares = [(q, ids.index(mid)) for mid, qs in sint.items() for q in qs]
    random.shuffle(pares)
    corte = int(len(pares) * 0.8)
    treino, valid = pares[:corte], pares[corte:]
    Qtr = embeddings([p[0] for p in treino], "query")
    Qva = embeddings([p[0] for p in valid], "query")
    print(f"{len(memorias)} memórias | {len(treino)} perguntas de treino | {len(valid)} de validação\n")

    W = treinar(Qtr, [p[1] for p in treino], Qva, [p[1] for p in valid], D)
    np.save(PASTA / "adaptador.npy", W)

    # PROVA FINAL: perguntas escritas à mão, nunca vistas no treino
    prova = [q for q in conjunto["perguntas"] if q["relevantes"]]
    Qp = embeddings([q["pergunta"] for q in prova], "query")
    rel = [[ids.index(r) for r in q["relevantes"]] for q in prova]
    antes, depois = medir(Qp, D, rel), medir(Qp, D, rel, W)
    print(f"\nPROVA FINAL — {len(prova)} perguntas escritas à mão (nunca vistas):")
    print(f"{'métrica':<10}{'sem adaptador':>16}{'com adaptador':>16}")
    for k in antes:
        f = (lambda v: f"{v:.2f}") if k == "MRR" else (lambda v: f"{v:.0%}")
        print(f"{k:<10}{f(antes[k]):>16}{f(depois[k]):>16}")

    # por pergunta: onde mudou
    Wq = Qp @ W
    Wq /= np.linalg.norm(Wq, axis=1, keepdims=True)
    for q, a, b in zip(prova, np.argsort(-(Qp @ D.T), axis=1), np.argsort(-(Wq @ D.T), axis=1)):
        if a[0] != b[0]:
            print(f"  {q['id']}: 1º lugar mudou de '{ids[a[0]]}' para '{ids[b[0]]}' (certo: {q['relevantes']})")
    (PASTA / "resultado_adaptador.json").write_text(json.dumps(
        {"sem_adaptador": {k: float(v) for k, v in antes.items()},
         "com_adaptador": {k: float(v) for k, v in depois.items()},
         "treino": len(treino), "validacao": len(valid), "epocas": EPOCAS, "tau": TAU, "lambda_reg": LAMBDA_REG},
        indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

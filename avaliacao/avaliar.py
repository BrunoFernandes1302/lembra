"""Avaliação do RAG do Lembra com "LLM como juiz".

Uso (precisa de GEMINI_API_KEY no ambiente ou no .env):
    python avaliacao/avaliar.py --rotulo chunk800
    python avaliacao/avaliar.py --rotulo chunk250 --chunk-size 250 --chunk-overlap 40
    python avaliacao/avaliar.py --so-busca            # só a busca: rápido e quase sem gastar cota
    python avaliacao/avaliar.py --conjunto conjunto_dificil.json --rotulo dificil   # conjunto com armadilhas
    python avaliacao/avaliar.py --repeticoes 3 --rotulo v1_x3   # repete cada pergunta (menos ruído)
    python avaliacao/avaliar.py --prompt avaliacao/prompts/v2_interpretar_sentido.txt --rotulo v2
                                                       # testa um prompt candidato sem mudar o app
    python avaliacao/comparar.py                       # compara os resultados salvos

O que mede:
  BUSCA (sem IA, por conta)
    - recall@K: das memórias que contêm a resposta, quantas apareceram entre os K trechos buscados
    - acerto@1: o 1º trecho veio de uma memória certa?
    - MRR: média de 1/posição da primeira memória certa (1 = sempre em 1º; 0,5 = em média 2º)
  RESPOSTA (o juiz decide, com justificativa)
    - correta: a resposta traz a informação essencial da resposta esperada?
    - fiel: toda afirmação está apoiada nas memórias entregues (não inventou)?
    - abstenção: nas perguntas SEM resposta, o Lembra admitiu que não sabe?

Decisões:
  - Roda num "banco em memória" (busca exata por cosseno) com o MESMO chunking, embeddings e LLM
    do app. Não suja o Supabase e é repetível. Não testa o índice HNSW do pgvector.
  - O juiz responde passou/não passou (binário) com justificativa: LLMs são inconsistentes com
    notas de 1 a 5 e bem mais confiáveis com critérios binários claros.
  - Limitação: o juiz é Gemini avaliando respostas do Gemini (viés de "autopreferência").
    Em produção, use um juiz de outra família e confira uma amostra à mão.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from pydantic import BaseModel

from lembra import rag
from lembra.chunking import chunk_text
from lembra.config import embedder_de, get_settings
from lembra.llm import get_llm
from lembra.supabase import Trecho

PASTA = Path(__file__).resolve().parent
NAO_SABE = "NAO_SABE"


# ---------------------------------------------------------------- banco em memória
class RepositorioEmMemoria:
    """Mesma interface do RepositorioSupabase, com busca EXATA por cosseno."""

    def __init__(self):
        self.chunks: list[dict] = []

    def adicionar(self, memoria: dict, textos: list[str], vetores: list[list[float]]):
        for t, v in zip(textos, vetores):
            self.chunks.append({"memoria_id": memoria["id"], "texto": t, "v": v,
                                "categoria": memoria["categoria"], "data": memoria["data_evento"]})

    def buscar(self, vetor, k, categoria=None, modelo=None) -> list[Trecho]:
        cand = [c for c in self.chunks if categoria is None or c["categoria"] == categoria]
        notas = [(sum(a * b for a, b in zip(c["v"], vetor)), c) for c in cand]  # vetores normalizados
        notas.sort(key=lambda x: -x[0])
        return [Trecho(c["texto"], {"memoria_id": c["memoria_id"], "categoria": c["categoria"],
                                    "data": c["data"]}, nota) for nota, c in notas[:k]]


# ---------------------------------------------------------------- chamadas com nova tentativa
def com_novas_tentativas(func, *args, tentativas=6, **kwargs):
    """O nível gratuito tem limite por minuto (429) e às vezes fica sobrecarregado (503):
    espera e tenta de novo, dobrando a espera (backoff exponencial)."""
    espera = 5
    for i in range(tentativas):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            msg = str(e)
            temporario = any(x in msg for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE", "500"))
            if not temporario or i == tentativas - 1 or "prepayment" in msg:
                raise
            print(f"    (limite/instabilidade da API, esperando {espera}s...)", flush=True)
            time.sleep(espera)
            espera = min(espera * 2, 60)


# ---------------------------------------------------------------- juiz
class Veredito(BaseModel):
    correta: bool
    fiel: bool
    justificativa: str


INSTRUCOES_JUIZ = """Você é um avaliador rigoroso de um assistente pessoal que responde com base nas \
memórias do usuário. Julgue a RESPOSTA DO ASSISTENTE com dois critérios independentes:

1. correta (true/false) — siga o TIPO DE PERGUNTA informado:
   - Tipo "TEM RESPOSTA": true somente se a resposta traz a informação essencial da RESPOSTA
     ESPERADA. Redação diferente é ok; detalhes extras verdadeiros são ok. Se o assistente disser
     que não encontrou/não sabe, é false (a informação existia; ele não a entregou).
   - Tipo "SEM RESPOSTA" (o usuário nunca registrou isso): true SOMENTE se o assistente disser que
     não encontrou ou não sabe, sem inventar uma resposta.

2. fiel (true/false):
   - true se TODAS as afirmações factuais da resposta estão apoiadas nas MEMÓRIAS ENTREGUES.
     Contas corretas feitas a partir delas contam como apoiadas. Dizer "não encontrei" é fiel.
     O assistente também sabe a DATA DE HOJE (informada abaixo): datas, anos, dias da semana e
     "quantos dias faltam" deduzidos dela + das memórias contam como apoiados.
   - false se afirmar qualquer coisa que não esteja nas memórias entregues, mesmo que pareça plausível.

Dê uma justificativa curta (1 a 2 frases), em português."""


def julgar(cliente, modelo: str, pergunta: str, esperada: str, trechos: list[Trecho], resposta: str,
           hoje: str | None = None) -> Veredito:
    from google.genai import types

    memorias = "\n\n".join(f"[{i}] {t.texto}" for i, t in enumerate(trechos, 1)) or "(nenhuma)"
    # Quem decide se a pergunta tem resposta é o CÓDIGO (nós sabemos), não a interpretação do juiz.
    if esperada == NAO_SABE:
        tipo, esperada_txt = "SEM RESPOSTA", "(o usuário nunca registrou essa informação)"
    else:
        tipo, esperada_txt = "TEM RESPOSTA", esperada
    # O juiz precisa saber a mesma "data de hoje" que o assistente recebeu; sem isso, "12/11/2026"
    # parece um ano inventado e respostas certas viram "não fiel".
    data = f"DATA DE HOJE (a mesma que o assistente recebeu): {hoje}\n\n" if hoje else ""
    conteudo = (f"{data}TIPO DE PERGUNTA: {tipo}\n\nPERGUNTA:\n{pergunta}\n\nRESPOSTA ESPERADA:\n{esperada_txt}\n\n"
                f"MEMÓRIAS ENTREGUES AO ASSISTENTE:\n{memorias}\n\nRESPOSTA DO ASSISTENTE:\n{resposta}")
    r = cliente.models.generate_content(
        model=modelo, contents=conteudo,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCOES_JUIZ, temperature=0,
            response_mime_type="application/json", response_schema=Veredito),
    )
    return r.parsed if isinstance(r.parsed, Veredito) else Veredito.model_validate_json(r.text)


# ---------------------------------------------------------------- métricas de busca
def medir_busca(trechos: list[Trecho], relevantes: list[str]) -> dict:
    ids = [t.metadados["memoria_id"] for t in trechos]
    if not relevantes:
        return {"recall": None, "acerto1": None, "rr": None, "nota_top1": trechos[0].similaridade if trechos else None}
    achadas = set(ids) & set(relevantes)
    pos = next((i for i, m in enumerate(ids, 1) if m in relevantes), None)
    return {"recall": len(achadas) / len(relevantes), "acerto1": bool(ids and ids[0] in relevantes),
            "rr": 1 / pos if pos else 0.0, "nota_top1": trechos[0].similaridade if trechos else None}


def media(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------- principal
def main():
    ap = argparse.ArgumentParser(description="Avalia o RAG do Lembra (LLM como juiz).")
    ap.add_argument("--rotulo", default="padrao", help="nome desta rodada (ex.: chunk250)")
    ap.add_argument("--chunk-size", type=int)
    ap.add_argument("--chunk-overlap", type=int)
    ap.add_argument("--top-k", type=int)
    ap.add_argument("--modelo-llm", help="modelo que responde (padrão: o do app)")
    ap.add_argument("--modelo-juiz", default="gemini-flash-lite-latest")
    ap.add_argument("--so-busca", action="store_true", help="mede só a busca (sem LLM nem juiz)")
    ap.add_argument("--pausa", type=float, default=2.0, help="segundos entre chamadas ao LLM")
    ap.add_argument("--repeticoes", type=int, default=1,
                    help="quantas vezes gerar+julgar cada pergunta (o LLM varia; mais repetições = menos ruído)")
    ap.add_argument("--conjunto", default="conjunto.json", help="arquivo do conjunto (ex.: conjunto_dificil.json)")
    ap.add_argument("--prompt", help="arquivo .txt com um prompt de sistema CANDIDATO (testa sem mudar o app)")
    a = ap.parse_args()

    if a.prompt:  # avalia um prompt candidato antes de levá-lo para o app
        rag.SYSTEM_PROMPT = Path(a.prompt).read_text(encoding="utf-8").strip()
    versao_prompt = hashlib.sha1(rag.SYSTEM_PROMPT.encode()).hexdigest()[:8]

    s = get_settings()
    s = replace(s, usar_ia=True, instrucoes="", llm_provider="gemini",
                chunk_size=a.chunk_size or s.chunk_size,
                chunk_overlap=a.chunk_overlap if a.chunk_overlap is not None else s.chunk_overlap,
                top_k=a.top_k or s.top_k,
                gemini_model=a.modelo_llm or s.gemini_model)
    conjunto = json.loads((PASTA / a.conjunto).read_text(encoding="utf-8"))
    # Data de referência FIXA do conjunto: perguntas como "qual a PRÓXIMA consulta?" dependem de hoje.
    # Com a data real, a resposta certa mudaria com o calendário e as rodadas deixariam de ser comparáveis.
    hoje = datetime.strptime(conjunto["hoje"], "%d/%m/%Y").date() if conjunto.get("hoje") else None
    print(f"Rodada '{a.rotulo}': chunk={s.chunk_size} sobreposição={s.chunk_overlap} top_k={s.top_k} "
          f"embeddings={s.embedding_model} llm={s.gemini_model} juiz={a.modelo_juiz} "
          f"prompt={versao_prompt}{' (' + a.prompt + ')' if a.prompt else ''} repetições={a.repeticoes}\n")

    # 1) indexar as memórias (um lote só de embeddings)
    repo = RepositorioEmMemoria()
    pedacos = [(m, chunk_text(m["texto"], s.chunk_size, s.chunk_overlap)) for m in conjunto["memorias"]]
    todos = [t for _, ts in pedacos for t in ts]
    vetores = com_novas_tentativas(embedder_de(s).embed_documents, todos)
    i = 0
    for m, ts in pedacos:
        repo.adicionar(m, ts, vetores[i : i + len(ts)])
        i += len(ts)
    print(f"Indexadas {len(conjunto['memorias'])} memórias em {len(todos)} chunks.\n")

    llm = None if a.so_busca else get_llm(s)
    juiz = None
    if not a.so_busca:
        from google import genai

        juiz = genai.Client(api_key=s.gemini_api_key)

    resultados = []
    for q in conjunto["perguntas"]:
        trechos = com_novas_tentativas(rag.buscar, repo, q["pergunta"], None, s)
        busca = medir_busca(trechos, q["relevantes"])
        item = {**q, "busca": busca, "fontes": [t.metadados["memoria_id"] for t in trechos]}
        linha = f"{q['id']} [{q['tipo']:<22}] "
        if q["relevantes"]:
            linha += f"recall={busca['recall']:.2f} acerto@1={'✓' if busca['acerto1'] else '✗'}"
        else:
            linha += f"(sem resposta; melhor nota {busca['nota_top1']:.2f})"

        if not a.so_busca:
            tentativas = []
            for _ in range(a.repeticoes):
                time.sleep(a.pausa)
                resposta = com_novas_tentativas(llm.gerar, rag.prompt_do_sistema(s),
                                                rag.montar_prompt(q["pergunta"], trechos, hoje=hoje))
                time.sleep(a.pausa)
                v = com_novas_tentativas(julgar, juiz, a.modelo_juiz, q["pergunta"], q["esperada"], trechos, resposta,
                                         hoje=(hoje or rag.hoje_em_sp()).strftime("%d/%m/%Y"))
                tentativas.append({"resposta": resposta, "correta": v.correta, "fiel": v.fiel,
                                   "justificativa": v.justificativa})
            # taxa de acerto nas repetições (ex.: 2 de 3 = 0,67)
            item.update(tentativas=tentativas,
                        correta=media(float(t["correta"]) for t in tentativas),
                        fiel=media(float(t["fiel"]) for t in tentativas))
            simb = lambda x: "✓" if x == 1 else ("✗" if x == 0 else f"{x:.0%}")
            linha += f" | correta={simb(item['correta'])} fiel={simb(item['fiel'])}"
        print(linha, flush=True)
        if not a.so_busca:
            for t in item["tentativas"]:
                if not (t["correta"] and t["fiel"]):
                    print(f"      resposta: {t['resposta'][:160]}\n      juiz: {t['justificativa']}")
        resultados.append(item)

    # 2) resumo
    com_resp = [r for r in resultados if r["relevantes"]]
    sem_resp = [r for r in resultados if not r["relevantes"]]
    resumo = {
        "recall@K": media(r["busca"]["recall"] for r in com_resp),
        "acerto@1": media(float(r["busca"]["acerto1"]) for r in com_resp),
        "MRR": media(r["busca"]["rr"] for r in com_resp),
    }
    if not a.so_busca:
        resumo.update({
            "correta": media(r["correta"] for r in resultados),
            "fiel": media(r["fiel"] for r in resultados),
            "abstencao_correta": media(r["correta"] for r in sem_resp),
        })
        por_tipo = {}
        for r in resultados:
            por_tipo.setdefault(r["tipo"], []).append(r["correta"])
        resumo["correta_por_tipo"] = {t: media(v) for t, v in sorted(por_tipo.items())}

    print("\nRESUMO")
    for k, v in resumo.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for t, x in v.items():
                print(f"     {t:<24} {x:.0%}")
        elif v is not None:
            print(f"  {k:<20} {v:.0%}" if k != "MRR" else f"  {k:<20} {v:.2f}")

    saida = PASTA / "resultados"
    saida.mkdir(exist_ok=True)
    arquivo = saida / f"{datetime.now():%Y%m%d-%H%M%S}_{a.rotulo}.json"
    arquivo.write_text(json.dumps({
        "rotulo": a.rotulo, "quando": datetime.now().isoformat(timespec="seconds"),
        "config": {"chunk_size": s.chunk_size, "chunk_overlap": s.chunk_overlap, "top_k": s.top_k,
                   "embeddings": s.embedding_model, "llm": None if a.so_busca else s.gemini_model,
                   "juiz": None if a.so_busca else a.modelo_juiz, "chunks_indexados": len(todos),
                   "prompt": versao_prompt, "prompt_arquivo": a.prompt, "repeticoes": a.repeticoes,
                   "conjunto": a.conjunto, "hoje": conjunto.get("hoje")},
        "resumo": resumo, "resultados": resultados,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSalvo em {arquivo.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

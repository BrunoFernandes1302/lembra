"""Fine-tuning, etapa 1: gerar DADOS SINTÉTICOS de treino.

Não podemos treinar com as perguntas da avaliação (seria "decorar a prova": a nota sobe sem o
modelo aprender nada). Então o Gemini INVENTA perguntas variadas para cada memória; treinamos com
elas e avaliamos com as perguntas escritas à mão (avaliacao/conjunto_dificil.json), que o
modelo nunca viu.

Uso:  python finetuning/gerar_dados.py      -> finetuning/dados/perguntas_sinteticas.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
sys.path.insert(0, str(RAIZ / "avaliacao"))

from pydantic import BaseModel  # noqa: E402

from avaliar import com_novas_tentativas  # noqa: E402
from lembra.config import get_settings  # noqa: E402

PASTA = Path(__file__).resolve().parent / "dados"


class PerguntasDaMemoria(BaseModel):
    id: str
    perguntas: list[str]


class Lote(BaseModel):
    itens: list[PerguntasDaMemoria]


INSTRUCOES = """Você cria dados de treino para um sistema de busca de memórias pessoais.
Para CADA memória recebida, escreva 6 perguntas que o dono da memória faria e que essa memória
responde. Varie bastante:
- 1 direta; 2 com outras palavras (sinônimos, termos mais gerais: "pet" para cachorra, "médico"
  para dentista); 1 coloquial/curta como alguém digitando no celular; 1 indireta (o que a pessoa
  quer saber, sem citar o assunto exato); 1 que use o contexto temporal se houver data.
- Em português do Brasil, na primeira pessoa ("meu", "eu").
- NÃO copie frases inteiras da memória; a pergunta deve soar natural.
Devolva o id de cada memória exatamente como recebido."""


def main():
    from google import genai
    from google.genai import types

    s = get_settings()
    cliente = genai.Client(api_key=s.gemini_api_key)
    memorias = json.loads((RAIZ / "avaliacao/conjunto_dificil.json").read_text(encoding="utf-8"))["memorias"]
    saida: dict[str, list[str]] = {}
    for i in range(0, len(memorias), 10):  # lotes de 10 memórias por chamada
        lote = memorias[i : i + 10]
        texto = "\n".join(f'- id="{m["id"]}" (data: {m["data_evento"] or "—"}): {m["texto"]}' for m in lote)

        def pedir():
            r = cliente.models.generate_content(
                model=s.gemini_model, contents=f"MEMÓRIAS:\n{texto}",
                config=types.GenerateContentConfig(system_instruction=INSTRUCOES, temperature=0.9,
                                                   response_mime_type="application/json", response_schema=Lote))
            return r.parsed if isinstance(r.parsed, Lote) else Lote.model_validate_json(r.text)

        for item in com_novas_tentativas(pedir).itens:
            if item.id in {m["id"] for m in lote}:
                saida[item.id] = [p.strip() for p in item.perguntas if p.strip()]
        print(f"lote {i // 10 + 1}: {sum(len(v) for v in saida.values())} perguntas até agora", flush=True)

    faltando = [m["id"] for m in memorias if m["id"] not in saida]
    PASTA.mkdir(exist_ok=True)
    (PASTA / "perguntas_sinteticas.json").write_text(json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Salvo: {sum(len(v) for v in saida.values())} perguntas para {len(saida)} memórias. Faltando: {faltando}")


if __name__ == "__main__":
    main()

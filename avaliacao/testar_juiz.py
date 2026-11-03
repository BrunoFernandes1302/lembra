"""Testa o JUIZ: ele reprova respostas que sabemos estar erradas?

Um juiz que aprova tudo dá 100% para qualquer sistema e não serve para nada. Aqui entregamos
respostas plantadas (certas e erradas, com o veredito que esperamos) e conferimos se ele acerta.

Uso:  python avaliacao/testar_juiz.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from avaliar import com_novas_tentativas, julgar  # noqa: E402
from lembra.config import get_settings  # noqa: E402
from lembra.supabase import Trecho  # noqa: E402

ALUGUEL = Trecho("Pago 1.800 reais de aluguel todo dia 5. O condomínio é 450 reais e vence no dia 10.", {}, 0.7)
MEL = Trecho("Tenho uma cachorra chamada Mel, vira-lata caramelo que adotei num abrigo em 2020.", {}, 0.7)

# (descrição, pergunta, esperada, trechos, resposta do "assistente", correta esperada, fiel esperada)
CASOS = [
    ("resposta certa", "Quanto gasto com moradia?", "2.250 reais (1.800 + 450).", [ALUGUEL],
     "Você gasta 2.250 reais por mês: 1.800 de aluguel e 450 de condomínio [1].", True, True),
    ("conta errada", "Quanto gasto com moradia?", "2.250 reais (1.800 + 450).", [ALUGUEL],
     "Você gasta 2.500 reais por mês com moradia [1].", False, False),
    ("certa, mas inventou um detalhe", "Qual o nome da minha cachorra?", "Mel.", [MEL],
     "Sua cachorra se chama Mel; ela é da raça golden retriever e tem 8 anos [1].", True, False),
    ("disse que não sabe, mas sabia", "Qual o nome da minha cachorra?", "Mel.", [MEL],
     "Não encontrei essa informação nas suas memórias.", False, True),
    # Caso real que enganou o juiz na 1ª versão: a busca não trouxe a memória certa, o assistente
    # admitiu honestamente (fiel), mas a resposta NÃO está correta (a informação existia).
    ("busca falhou, admitiu honesto", "Qual o nome da minha cachorra?", "Mel.", [ALUGUEL],
     "Não encontrei o nome da sua cachorra nas suas memórias.", False, True),
    ("inventou em vez de admitir", "Qual é o meu tipo sanguíneo?", "NAO_SABE", [MEL],
     "Seu tipo sanguíneo é O positivo.", False, False),
    ("admitiu corretamente", "Qual é o meu tipo sanguíneo?", "NAO_SABE", [MEL],
     "Não encontrei isso nas suas memórias.", True, True),
]


def main():
    from google import genai

    s = get_settings()
    cliente = genai.Client(api_key=s.gemini_api_key)
    acertos = 0
    for desc, perg, esp, trechos, resp, c_esp, f_esp in CASOS:
        v = com_novas_tentativas(julgar, cliente, "gemini-flash-lite-latest", perg, esp, trechos, resp)
        ok = v.correta == c_esp and v.fiel == f_esp
        acertos += ok
        print(f"{'✓' if ok else '✗'} {desc:<32} juiz: correta={v.correta!s:<5} fiel={v.fiel!s:<5}"
              f" (esperado {c_esp!s:<5}/{f_esp!s:<5})")
        if not ok:
            print(f"     justificativa: {v.justificativa}")
        time.sleep(2)
    print(f"\nO juiz acertou {acertos} de {len(CASOS)} casos plantados.")


if __name__ == "__main__":
    main()

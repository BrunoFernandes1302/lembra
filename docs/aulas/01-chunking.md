# Aula 1 — Chunking

## O problema

Um modelo de embeddings transforma um texto em **um único vetor**. Imagine que você escreveu
uma memória longa sobre sua infância, sua primeira viagem e seu primeiro emprego. Um vetor só
para tudo isso vira uma "média" dos três assuntos — e a pergunta *"qual foi meu primeiro
emprego?"* não vai casar bem com nenhum deles.

**Solução:** quebrar o texto em pedaços menores e focados — os *chunks*. Cada chunk ganha seu
próprio vetor, e a busca encontra exatamente o pedaço relevante.

## Os dois botões

| Parâmetro | Muito pequeno | Muito grande |
|-----------|---------------|--------------|
| `chunk_size` | Pedaço perde contexto ("ela adotou em 2020" — ela quem?) | Vetor genérico, busca imprecisa |
| `overlap` | Informação na fronteira entre chunks se perde | Duplicação, mais custo |

Valores comuns para começar: **500–1000 caracteres** com **10–20% de overlap**.

## A estratégia recursiva

Cortar a cada N caracteres é fácil, mas quebra palavras e frases no meio. A abordagem mais
usada respeita a estrutura do texto, do separador "mais forte" para o "mais fraco":

```
"\n\n" (parágrafo)  →  "\n" (linha)  →  ". " (frase)  →  " " (palavra)  →  corte bruto
```

1. Tente dividir pelo separador mais forte.
2. Algum pedaço ainda ficou grande demais? Divida **só ele** pelo próximo separador.
3. Agora você tem vários pedaços pequenos. **Junte** pedaços vizinhos enquanto couberem em `chunk_size`.
4. Ao fechar um chunk, comece o próximo repetindo o "rabo" do anterior (até `overlap` caracteres).

## Exercício

Implemente `chunk_text` em [`src/segundo_cerebro/chunking.py`](../../src/segundo_cerebro/chunking.py).

```bash
pytest tests/test_chunking.py -v
```

Sugestão de ordem (faça um teste passar de cada vez):

1. `test_parametros_invalidos` e `test_texto_vazio_retorna_lista_vazia` — aquecimento.
2. `test_texto_curto_vira_um_chunk`.
3. `test_nenhum_chunk_passa_do_limite` — aqui você pode começar com **corte bruto** a cada `chunk_size`. Funciona, mas o próximo teste vai falhar...
4. `test_nao_corta_palavras_quando_ha_espaco` e `test_prefere_quebrar_por_paragrafo` — hora da recursão.
5. `test_chunks_vizinhos_tem_sobreposicao` e `test_nada_se_perde` — o overlap.

Dicas, se travar:
- Separe em duas funções auxiliares: uma que **divide** (recursiva) e outra que **junta**.
- `texto.split(sep)` remove o separador — lembre de recolocá-lo para o texto não "grudar".
- Para o overlap, guarde os pedaços do chunk atual numa lista e, ao fechar o chunk, remova do *início* até sobrar ≤ `overlap` caracteres.

## Para refletir (responda antes da Aula 2)

1. Por que preferir quebrar em parágrafo antes de frase?
2. Se suas memórias forem frases curtas (tipo "Meu tipo sanguíneo é O+"), o chunking muda alguma coisa?
3. Depois de passar nos testes: compare com o `RecursiveCharacterTextSplitter` do LangChain. O que ele faz diferente?

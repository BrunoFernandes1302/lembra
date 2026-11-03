# Roadmap

Cada fase tem: **conceito** (o que aprender), **entrega** (o que fica funcionando) e
**pergunta-chave** (o que você deve conseguir explicar ao final).

## Fase 1 — Chunking
- **Conceito:** por que não indexar o texto inteiro; tamanho de chunk vs. precisão; overlap.
- **Entrega:** `chunk_text()` passando em `tests/test_chunking.py`.
- **Pergunta-chave:** o que acontece com a busca se o chunk for grande demais? E pequeno demais?

## Fase 2 — Embeddings
- **Conceito:** texto → vetor; similaridade de cosseno; por que modelo multilíngue; prefixos `query:`/`passage:` da família E5.
- **Entrega:** módulo que gera embeddings + experimento comparando frases parecidas e diferentes.
- **Pergunta-chave:** por que "minha cachorra Mel" fica perto de "meu pet" mesmo sem palavras em comum?

## Fase 3 — Banco vetorial e busca
- **Conceito:** ChromaDB, metadados (data, categoria), top-K, **fonte da verdade separada do índice** (`memorias.jsonl` × `chroma/`).
- **Entrega:** comando para salvar uma memória e comando para buscar os trechos mais parecidos.
- **Pergunta-chave:** se eu trocar o modelo de embeddings, o que precisa ser refeito?

## Fase 4 — Geração (o "G" do RAG)
- **Conceito:** montar o prompt com contexto, instruir o modelo a responder só com as fontes, citar `[1]`, admitir quando não sabe; API do Claude.
- **Entrega:** pergunta → resposta com fontes no terminal.
- **Pergunta-chave:** como o sistema evita "inventar" uma memória que não existe?

## Fase 5 — Interface
- **Conceito:** Streamlit, estado de sessão, dois fluxos (alimentar e perguntar).
- **Entrega:** app com as duas abas.

## Fase 6 — Avaliação e RAG avançado
- **Conceito:** conjunto de perguntas de teste, métricas (recall@K, fidelidade), busca híbrida (BM25 + vetorial), re-ranking, filtros por metadado, conversas com histórico.
- **Entrega:** script de avaliação e pelo menos uma melhoria medida com números.
- **Pergunta-chave:** como provar que uma mudança melhorou o RAG, e não só "parece melhor"?

## Fase 7 — LLM local
- **Conceito:** Ollama, quantização (GGUF, Q4/Q8), trade-off qualidade × hardware × privacidade.
- **Entrega:** trocar o LLM por um modelo local só mudando o `.env`.

## Fase 8 — Fine-tuning
- **Conceito:** quando fine-tuning faz sentido (estilo/formato) e quando RAG é melhor (conhecimento); LoRA/QLoRA; montar dataset.
- **Entrega:** um modelo pequeno ajustado para responder no seu estilo, comparado com o modelo base.
- **Pergunta-chave:** por que não usar fine-tuning para "ensinar" fatos da sua vida?

## Fase 9 — Levando para a empresa
- **Conceito:** documentos reais (PDF, Confluence, etc.), permissões por usuário, LGPD, banco vetorial de produção (pgvector/Qdrant), custos, observabilidade.
- **Entrega:** documento de proposta/arquitetura para um piloto interno.

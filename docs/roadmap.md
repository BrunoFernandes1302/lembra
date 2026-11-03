# Roadmap

| Fase | Tema | O que se aprende | Status |
|------|------|------------------|--------|
| 1 | **RAG básico** | Chunking, embeddings, banco vetorial, prompt com contexto | ✅ |
| 2 | **Avaliação** | Como *medir* se o RAG está bom: perguntas de teste, recall@K, fidelidade | ⬜ |
| 3 | **RAG avançado** | Busca híbrida (BM25 + vetor), re-ranking, filtros por metadado, chat com histórico | ⬜ |
| 4 | **LLM local** | Ollama, quantização, trade-off qualidade × hardware × privacidade | ⬜ |
| 5 | **Fine-tuning** | Quando faz sentido, LoRA/QLoRA, montar dataset, comparar com o modelo base | ⬜ |
| 6 | **Empresa** | PDFs/Confluence, permissões por usuário, LGPD, pgvector, custos, observabilidade | ⬜ |

## Perguntas que você deve saber responder ao fim de cada fase

1. **RAG básico:** por que quebrar em chunks? Por que a busca por embeddings acha "pet" quando a memória diz "cachorra"? O que acontece se eu trocar o modelo de embeddings?
2. **Avaliação:** como provar que uma mudança melhorou o sistema, e não só que "parece melhor"?
3. **RAG avançado:** quando a busca por palavra-chave ganha da busca vetorial?
4. **LLM local:** o que eu perco e o que eu ganho rodando localmente?
5. **Fine-tuning:** por que não usar fine-tuning para "ensinar" fatos da minha vida?
6. **Empresa:** como garantir que um funcionário não receba trechos de documentos que ele não pode ver?

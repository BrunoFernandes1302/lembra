# Roadmap

Forma de trabalho: **usar no dia a dia → anotar problemas → corrigir entendendo o porquê.**
Cada problema encontrado vira uma *issue* no GitHub (aba Issues), com o que foi perguntado, o que
o sistema respondeu e o que era esperado.

| Fase | Tema | O que se aprende | Status |
|------|------|------------------|--------|
| 1 | **RAG básico** | Chunking, embeddings, banco vetorial, prompt com contexto | ✅ |
| 2 | **App de verdade** | PWA mobile (botão de instalar, atalhos, aviso sem internet), login/senha, multiusuário isolado, deploy, banco na nuvem | ✅ no ar em lembra-nu.vercel.app |
| 3 | **Categorias e configuração do RAG** | Categorias por usuário, filtros, editar memória, ajustes do RAG no app, Laboratório, IA sugere categoria | ✅ |
| 4 | **Avaliação (LLM-as-judge)** | Conjunto de perguntas de teste, recall@K, fidelidade; um LLM "juiz" avalia as respostas | ✅ conjunto difícil com 40 perguntas (correta 98%, tempo 100%); próximo: dificultar a busca |
| 5 | **Agentes** | LLM que decide quais ferramentas usar (buscar, listar, calcular, contar dias) | ✅ experimental |
| 6 | **RAG avançado** | Busca híbrida, re-ranking, chat com histórico | 🟡 conversa com memória (reescrita da pergunta) ✅; busca híbrida e re-ranking ⬜ |
| 7 | **LLM local** | Ollama, quantização, privacidade | 🟡 LoRA avaliado (correta 50→60%, fiel 70→80%, admite não saber 0→50%); falta servir no Ollama |
| 8 | **Fine-tuning** | Congelar o modelo e treinar só a "ponta" / LoRA | ✅ experimentos (adaptador de embeddings e LoRA) |
| 8b | **Visual e integrações** | Redesenho moderno "cara de IA" ✅ v1; importar conversas do WhatsApp ✅; Lembra como contato no WhatsApp (API oficial) 🟡 no ar e configurado; aguardando a Meta liberar envio para o Brasil (erro 130497); importação até 10 MB ✅ | 🟡 |
| 8c | **Multimodal** | Áudio (falar em vez de digitar) ✅; imagens (fotos de recibos, documentos) ⬜ futuro | 🟡 |
| 9 | **Empresa** | Documentos reais, permissões, LGPD (exportar e apagar conta ✅), custos | 🟡 |

## Detalhes

### 2. App de verdade (ver docs/visao-do-produto.md)
- O Streamlit serve para protótipo, mas não vira um bom PWA mobile nem tem login multiusuário de verdade.
- Proposta: **frontend PWA** (celular) + **API em Python** (o RAG atual) + **Supabase** (login, Postgres com pgvector e isolamento por usuário via *Row Level Security*).

### 3. Categorias (finanças, compromissos, família…)
- Hoje a categoria já é salva como **metadado** de cada chunk, mas ainda não é usada na busca.
- Próximo: **filtrar** a busca por categoria ("quanto gastei…" → só `finanças`).
- Depois: o LLM **classifica sozinho** a memória ao salvar, sem você escolher.
- Por que filtrar ajuda: menos candidatos significa menos ruído e trechos mais relevantes no prompt.

### 5. Agentes
- Hoje o fluxo é **fixo**: sempre busca e depois responde.
- Com um agente, o LLM recebe **ferramentas** (funções) e decide quais usar e em que ordem: por exemplo "buscar em finanças", depois "somar valores", depois "responder".
- Dados estruturados (valor de um gasto, data de um compromisso) ficam melhor numa **tabela** do que em chunks de texto. O agente consulta a tabela para fazer conta e o RAG para buscar histórias.

### 8. Fine-tuning "só a ponta"
- **Congelar o corpo e treinar a ponta** (*transfer learning*): o modelo pré-treinado fica intacto e só a última camada aprende. É barato e rápido.
- **LoRA**: é a versão moderna dessa ideia para LLMs. O modelo base fica congelado e se treinam pequenas matrizes "acopladas" a ele (menos de 1% dos parâmetros). O **QLoRA** faz o mesmo com o modelo comprimido em 4 bits, o que cabe numa GPU grátis do Google Colab.
- Dois alvos possíveis: (a) o **modelo de embeddings**, para melhorar a busca no seu vocabulário; (b) o **LLM**, para responder no seu estilo.
- Lembrete: fine-tuning ensina **comportamento**; os **fatos** continuam vindo do RAG.

## Perguntas que você deve saber responder ao fim de cada fase

1. **RAG básico:** por que quebrar em chunks? Por que a busca acha "pet" quando a memória diz "cachorra"?
2. **App de verdade:** como garantir que o usuário A nunca veja dados do usuário B, mesmo se houver um bug no código?
3. **Categorias:** filtrar por metadado antes da busca vetorial melhora o quê, e piora o quê?
4. **Avaliação:** como provar que uma mudança melhorou o sistema?
5. **Agentes:** qual a diferença entre um fluxo fixo e um agente? Quando o agente *não* vale a pena?
6. **RAG avançado:** quando a busca por palavra-chave ganha da busca vetorial?
7. **LLM local:** o que se perde e o que se ganha rodando localmente?
8. **Fine-tuning:** por que treinar só uma parte do modelo funciona quase tão bem quanto treinar tudo?
9. **Empresa:** como garantir que um funcionário não veja trechos de documentos que ele não pode ver?

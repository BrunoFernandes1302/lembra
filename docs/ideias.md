# Ideias e próximos passos

Lista viva. Cada ideia tem o **conceito de IA/engenharia** que ela ensina.

## Em andamento

### Lembra no WhatsApp (bot oficial)
- **O que:** o Lembra como contato. Encaminhar mensagens vira memória; mandar áudio vira memória
  transcrita; perguntar responde ali mesmo, com fontes.
- **Como:** WhatsApp Cloud API (oficial, Meta). Toda mensagem recebida chega à nossa API por um
  **webhook**; respondemos pela API da Meta.
- **Problemas a resolver:**
  1. *Vincular número ↔ conta:* código de 8 caracteres gerado no app ("VINCULAR K7PX2MQA"), uso único, 10 min.
  2. *Segurança do webhook:* conferir a assinatura HMAC (`X-Hub-Signature-256`) de cada chamada.
  3. *Agir sem o login do usuário:* ~~chave de serviço com filtro manual~~ → **decidido:** o
     servidor emite um crachá (JWT) de 5 min para o dono do número, e o RLS continua valendo
     (ver `docs/conceitos.md`, seção 11.1).
- **Status:** 🟡 no ar e configurado (app Meta publicado, webhook assinado, mensagens chegando). A Meta
  bloqueia o envio para o Brasil (erro 130497) até liberar a conta; se não liberar: verificação da
  empresa ou número brasileiro próprio. Falta também um token permanente (o temporário vence em 24 h).
- **Precisa do dono:** conta de desenvolvedor Meta + app com WhatsApp (número de teste é grátis).
- **Conceitos:** webhooks, assinaturas HMAC, autenticação entre serviços, idempotência (a Meta
  pode reenviar a mesma mensagem; não podemos salvar duas vezes).

## Próximas ideias

| Ideia | O que faz | Conceito que ensina |
|-------|-----------|---------------------|
| **Imagens** | Foto de recibo, receita médica, documento → texto e memória | Modelos multimodais com visão; extração estruturada (valor, data, CNPJ) |
| **Lembretes proativos** | "Seu dentista é amanhã às 14h" (notificação no celular) | Extração de datas com LLM; agendamento (cron); Web Push |
| **Resumo semanal** | "Esta semana você gastou R$ 1.230, teve 2 consultas…" | Sumarização; agregação; agentes que rodam sozinhos |
| **Memórias que se atualizam** | Ao registrar "aluguel subiu para 2.000", sugerir arquivar a antiga | Detecção de conflito/contradição; versionamento de fatos |
| **Busca híbrida** | Palavra-chave (BM25) + significado (vetores) | Quando a palavra exata importa (nomes, placas, códigos) |
| **Re-ranking** | Um segundo modelo reordena os 20 melhores trechos | Cross-encoders; precisão × custo |
| **Conversa com memória** | "E no mês passado?" entende o contexto da pergunta anterior | Histórico de chat; reescrita de pergunta |
| **Lembra 100% local** | Modelo pequeno com LoRA (já treinado em `finetuning/`) rodando no Ollama | Quantização (GGUF), servir modelos, privacidade |
| **Exportar meus dados** | Baixar tudo em JSON/PDF; apagar conta | LGPD (portabilidade e eliminação) |
| **Compartilhar com a família** | Memórias "da casa" visíveis a várias contas | RLS com grupos; permissões |
| **Painel de custo e uso** | Quantas chamadas à IA, tempo de resposta, falhas | Observabilidade; métricas de produto |

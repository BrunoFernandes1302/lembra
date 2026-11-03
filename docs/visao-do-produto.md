# Visão do produto

> Registro do que o dono do projeto deseja. Toda decisão técnica deve respeitar isto.

## O que é
Um **app de organização da vida pessoal** com IA: a pessoa registra memórias, finanças,
compromissos, família etc., e conversa com um assistente que conhece a vida dela e responde com
base no que ela mesma registrou.

## Para quem
1. Primeiro, o dono do projeto, no uso diário.
2. Depois, um **grupo de testadores** convidados.
3. No futuro, oferecer ao público (o nome precisa ser comercial) e aplicar o aprendizado na empresa.

## Requisitos obrigatórios
- **Mobile first:** a experiência principal é no celular.
- **PWA** (*Progressive Web App*): instalável na tela inicial, abre em tela cheia como um app nativo, sem passar pela App Store/Play Store.
- **Login e senha:** cada pessoa tem sua conta.
- **Isolamento total entre usuários:** um usuário nunca pode ver memórias de outro. É requisito de segurança e de LGPD.
- **Categorias:** finanças, compromissos, família etc. O usuário pode **criar, renomear e organizar** as próprias categorias e **mover memórias** entre elas.
- **Editar memórias**, não só criar e apagar.
- **Configurar o RAG dentro do app** (área avançada/"laboratório"): tamanho do chunk, sobreposição, quantos trechos buscar, modelo de IA, ver como cada memória foi quebrada em chunks e as notas de similaridade. No futuro, ligar e desligar **agentes**. Objetivo duplo: o dono aprende vendo os efeitos, e testadores comuns não precisam mexer (bons valores padrão).

## Integrações desejadas
- **WhatsApp:** escolher **conversas específicas** para entrar no Lembra e depois consultá-las perguntando.
  Limite técnico: a API oficial do WhatsApp não lê conversas pessoais (só mensagens enviadas a um
  número de empresa). Caminho recomendado: **exportar a conversa** (⋮ → Exportar conversa) e enviar
  o arquivo ao Lembra; alternativa: encaminhar mensagens a um número do Lembra. Bibliotecas não
  oficiais violam os termos e podem banir o número.
- Outras ferramentas do dia a dia (a definir).

## Forma de trabalho (ciclo de melhoria)
1. Usuários usam no dia a dia.
2. Problemas são relatados (issues no GitHub).
3. O Claude corrige **e explica o conceito por trás** da correção.
4. Repete.

## Objetivo de aprendizado
O dono quer **dominar** IA aplicada: RAG, avaliação, agentes, LLM local e fine-tuning
(congelar o modelo e treinar só uma parte / LoRA). O foco são os conceitos; o Claude escreve o código.

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
- **Categorias:** finanças, compromissos, família etc.

## Forma de trabalho (ciclo de melhoria)
1. Usuários usam no dia a dia.
2. Problemas são relatados (issues no GitHub).
3. O Claude corrige **e explica o conceito por trás** da correção.
4. Repete.

## Objetivo de aprendizado
O dono quer **dominar** IA aplicada: RAG, avaliação, agentes, LLM local e fine-tuning
(congelar o modelo e treinar só uma parte / LoRA). O foco são os conceitos; o Claude escreve o código.

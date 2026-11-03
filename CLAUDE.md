# Instruções para o Claude neste repositório

**Leia primeiro: [`docs/visao-do-produto.md`](docs/visao-do-produto.md)**, onde está o que o dono deseja.

Resumo: app de organização da vida pessoal com IA (RAG), **mobile, PWA, com login e senha**,
multiusuário com isolamento total de dados, testado por um grupo de pessoas num ciclo
"usar → relatar problema → corrigir explicando".

## Como trabalhar com o dono
- **O Claude escreve o código.** O dono quer dominar os **conceitos**, não programar.
- **Explique cada passo enquanto faz**: o que, por quê, quais alternativas existiam e quais trade-offs. Não faça várias coisas em silêncio e explique só no fim.
- Ao corrigir um problema relatado, explique a causa raiz e o conceito de IA/engenharia envolvido.
- Mantenha atualizados `docs/conceitos.md` (cada novo conceito) e `docs/roadmap.md` (status).
- Não crie aulas nem exercícios.
- Responda em português do Brasil.

## Regras
- Nunca versione nada de `data/` nem `.env` (dados pessoais e segredos).
- Toda mudança passa pelos testes (`pytest`) antes do push.

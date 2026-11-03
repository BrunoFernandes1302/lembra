-- Configurações do RAG por usuário. Sem linha = usa os padrões do servidor.
-- Os limites ficam no banco: valor absurdo não entra nem chamando a API direto.
create table public.config_rag (
  user_id              uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  chunk_size           int     not null default 800  check (chunk_size between 200 and 3000),
  chunk_overlap        int     not null default 150  check (chunk_overlap >= 0 and chunk_overlap * 2 < chunk_size),
  top_k                int     not null default 5    check (top_k between 1 and 20),
  margem_relevancia    real    not null default 0.05 check (margem_relevancia between 0 and 0.5),
  usar_ia              boolean not null default true,
  modelo_llm           text    not null default 'gemini-flash-lite-latest'
                               check (modelo_llm in ('gemini-flash-lite-latest', 'gemini-flash-latest')),
  instrucoes           text    not null default '' check (length(instrucoes) <= 500),
  atualizado_em        timestamptz not null default now()
);
alter table public.config_rag enable row level security;
create policy "dono le sua config"     on public.config_rag for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono cria sua config"   on public.config_rag for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "dono altera sua config" on public.config_rag for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "dono apaga sua config"  on public.config_rag for delete to authenticated using ((select auth.uid()) = user_id);

-- 👍/👎 em cada resposta: dados para personalizar agora e para fine-tuning no futuro.
create table public.feedback (
  id         bigint generated always as identity primary key,
  user_id    uuid not null default auth.uid() references auth.users (id) on delete cascade,
  pergunta   text not null check (length(pergunta) <= 2000),
  resposta   text not null check (length(resposta) <= 6000),
  util       boolean not null,
  comentario text check (length(comentario) <= 500),
  criado_em  timestamptz not null default now()
);
alter table public.feedback enable row level security;
create policy "dono le seu feedback"   on public.feedback for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono cria seu feedback" on public.feedback for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "dono apaga seu feedback" on public.feedback for delete to authenticated using ((select auth.uid()) = user_id);
create index feedback_user_idx on public.feedback (user_id, criado_em desc);

-- Perfil de estilo aprendido (personalização SEM treino: vai nas instruções da IA). Visível e editável.
alter table public.config_rag
  add column perfil_estilo text not null default '' check (length(perfil_estilo) <= 800),
  add column perfil_atualizado_em timestamptz;

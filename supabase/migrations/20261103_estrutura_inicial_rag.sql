-- Estrutura inicial do Lembra no Supabase (aplicada no projeto "lembra", região sa-east-1).
-- Explicação de cada decisão: docs/conceitos.md, seção "Multiusuário e segurança".

-- pgvector: permite guardar vetores e calcular distância entre eles
create extension if not exists vector with schema extensions;

-- FONTE DA VERDADE: o texto original que a pessoa escreveu
create table public.memorias (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null default auth.uid() references auth.users (id) on delete cascade,
  texto        text not null check (length(trim(texto)) > 0),
  categoria    text not null default 'geral',
  data_evento  text,                       -- quando aconteceu (texto livre: "2020", "março de 2018")
  criado_em    timestamptz not null default now()
);

-- ÍNDICE DE BUSCA: pedaços (chunks) com seus vetores (embeddings)
create table public.chunks (
  id          bigint generated always as identity primary key,
  memoria_id  uuid not null references public.memorias (id) on delete cascade,
  user_id     uuid not null default auth.uid() references auth.users (id) on delete cascade,
  indice      int  not null,               -- posição do chunk dentro da memória
  texto       text not null,
  categoria   text not null,               -- copiada da memória para filtrar a busca sem JOIN
  embedding   extensions.vector(384) not null,  -- 384 = tamanho do vetor do multilingual-e5-small
  unique (memoria_id, indice)
);

create index memorias_user_idx on public.memorias (user_id, criado_em desc);
create index chunks_user_categoria_idx on public.chunks (user_id, categoria);
create index chunks_memoria_idx on public.chunks (memoria_id);
-- HNSW: "mapa de vizinhos" para achar vetores próximos rápido (distância de cosseno)
create index chunks_embedding_idx on public.chunks
  using hnsw (embedding extensions.vector_cosine_ops);

-- ROW LEVEL SECURITY: o próprio banco garante que cada um só vê o que é seu
alter table public.memorias enable row level security;
alter table public.chunks   enable row level security;

create policy "dono le suas memorias"      on public.memorias for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono cria suas memorias"    on public.memorias for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "dono altera suas memorias"  on public.memorias for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "dono apaga suas memorias"   on public.memorias for delete to authenticated using ((select auth.uid()) = user_id);

create policy "dono le seus chunks"     on public.chunks for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono cria seus chunks"   on public.chunks for insert to authenticated with check (
  (select auth.uid()) = user_id
  and exists (select 1 from public.memorias m where m.id = memoria_id and m.user_id = (select auth.uid()))
);
create policy "dono apaga seus chunks"  on public.chunks for delete to authenticated using ((select auth.uid()) = user_id);

-- BUSCA: vizinhos mais próximos da pergunta, com filtro opcional por categoria.
-- security invoker = roda com as permissões de quem chamou, então o RLS continua valendo.
create or replace function public.buscar_chunks(
  query_embedding  extensions.vector(384),
  k                int  default 5,
  filtro_categoria text default null
)
returns table (
  id bigint, memoria_id uuid, indice int, texto text, categoria text,
  data_evento text, similaridade float
)
language sql stable security invoker
set search_path = ''
as $$
  select c.id, c.memoria_id, c.indice, c.texto, c.categoria, m.data_evento,
         1 - (c.embedding operator(extensions.<=>) query_embedding) as similaridade
  from public.chunks c
  join public.memorias m on m.id = c.memoria_id
  where filtro_categoria is null or c.categoria = filtro_categoria
  order by c.embedding operator(extensions.<=>) query_embedding
  limit least(greatest(k, 1), 50);
$$;

revoke execute on function public.buscar_chunks from public, anon;
grant  execute on function public.buscar_chunks to authenticated;

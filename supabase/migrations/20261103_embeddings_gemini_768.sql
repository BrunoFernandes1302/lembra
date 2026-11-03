-- Troca de modelo de embeddings: multilingual-e5-small (384) -> gemini-embedding-001 (768).
-- Banco vazio no momento da troca, então nada precisou ser reprocessado.
drop index if exists public.chunks_embedding_idx;
alter table public.chunks alter column embedding type extensions.vector(768);

-- Cada vetor registra o modelo que o gerou: vetores de modelos diferentes não são comparáveis.
alter table public.chunks add column modelo_embedding text not null default 'gemini-embedding-001';

create index chunks_embedding_idx on public.chunks
  using hnsw (embedding extensions.vector_cosine_ops);

drop function if exists public.buscar_chunks(extensions.vector, int, text);
create or replace function public.buscar_chunks(
  query_embedding  extensions.vector(768),
  k                int  default 5,
  filtro_categoria text default null,
  modelo           text default 'gemini-embedding-001'
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
  where (filtro_categoria is null or c.categoria = filtro_categoria)
    and c.modelo_embedding = modelo
  order by c.embedding operator(extensions.<=>) query_embedding
  limit least(greatest(k, 1), 50);
$$;
revoke execute on function public.buscar_chunks from public, anon;
grant  execute on function public.buscar_chunks to authenticated;

create or replace function public.salvar_memoria(
  p_texto       text,
  p_categoria   text,
  p_data_evento text,
  p_chunks      jsonb,   -- [{"indice": 0, "texto": "...", "embedding": "[0.1, ...]"}, ...]
  p_modelo      text default 'gemini-embedding-001'
)
returns uuid language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_id uuid;
  v_categoria text := coalesce(nullif(lower(trim(p_categoria)), ''), 'geral');
begin
  if p_chunks is null or jsonb_typeof(p_chunks) <> 'array' or jsonb_array_length(p_chunks) = 0 then
    raise exception 'A memória precisa de pelo menos um chunk';
  end if;

  insert into public.memorias (texto, categoria, data_evento)
  values (p_texto, v_categoria, nullif(trim(p_data_evento), ''))
  returning id into v_id;

  insert into public.chunks (memoria_id, indice, texto, categoria, embedding, modelo_embedding)
  select v_id, (c ->> 'indice')::int, c ->> 'texto', v_categoria,
         (c ->> 'embedding')::extensions.vector, p_modelo
  from jsonb_array_elements(p_chunks) as c;

  return v_id;
end $$;
drop function if exists public.salvar_memoria(text, text, text, jsonb);
revoke execute on function public.salvar_memoria from public, anon;
grant  execute on function public.salvar_memoria to authenticated;

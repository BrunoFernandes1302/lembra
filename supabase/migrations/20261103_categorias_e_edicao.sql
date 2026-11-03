-- Categorias personalizadas por usuário, edição de memória e operações de categoria.
-- Aplicada no projeto em duas etapas (a política de UPDATE em chunks veio logo depois).

create table public.categorias (
  id        uuid primary key default gen_random_uuid(),
  user_id   uuid not null default auth.uid() references auth.users (id) on delete cascade,
  nome      text not null check (nome = lower(trim(nome)) and length(nome) between 1 and 40),
  criado_em timestamptz not null default now(),
  unique (user_id, nome)
);
alter table public.categorias enable row level security;
create policy "dono le suas categorias"     on public.categorias for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono cria suas categorias"   on public.categorias for insert to authenticated with check ((select auth.uid()) = user_id);
create policy "dono altera suas categorias" on public.categorias for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
create policy "dono apaga suas categorias"  on public.categorias for delete to authenticated using ((select auth.uid()) = user_id);

-- Sem esta política, updates em chunks (renomear categoria, editar memória) afetariam 0 linhas em silêncio.
create policy "dono altera seus chunks" on public.chunks for update to authenticated
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

create or replace function public.criar_categorias_padrao()
returns trigger language plpgsql security definer set search_path = '' as $$
begin
  insert into public.categorias (user_id, nome)
  select new.id, c from unnest(array['geral','família','finanças','compromissos','trabalho',
                                     'saúde','viagens','estudos','gostos']) as c
  on conflict do nothing;
  return new;
end $$;
revoke execute on function public.criar_categorias_padrao from public, anon, authenticated;
create trigger categorias_padrao after insert on auth.users
  for each row execute function public.criar_categorias_padrao();

create or replace function public.normalizar_categoria(p text)
returns text language sql immutable set search_path = '' as $$
  select coalesce(nullif(lower(trim(p)), ''), 'geral')
$$;

create or replace function public.listar_categorias()
returns table (nome text, memorias bigint)
language sql stable security invoker set search_path = '' as $$
  select c.nome, count(m.id)
  from public.categorias c
  left join public.memorias m on m.user_id = c.user_id and m.categoria = c.nome
  group by c.nome
  order by c.nome = 'geral' desc, c.nome;
$$;

create or replace function public.salvar_memoria(
  p_texto text, p_categoria text, p_data_evento text, p_chunks jsonb,
  p_modelo text default 'gemini-embedding-001'
)
returns uuid language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_id uuid;
  v_categoria text := public.normalizar_categoria(p_categoria);
begin
  if p_chunks is null or jsonb_typeof(p_chunks) <> 'array' or jsonb_array_length(p_chunks) = 0 then
    raise exception 'A memória precisa de pelo menos um chunk';
  end if;
  insert into public.categorias (nome) values (v_categoria) on conflict do nothing;
  insert into public.memorias (texto, categoria, data_evento)
  values (p_texto, v_categoria, nullif(trim(p_data_evento), ''))
  returning id into v_id;
  insert into public.chunks (memoria_id, indice, texto, categoria, embedding, modelo_embedding)
  select v_id, (c ->> 'indice')::int, c ->> 'texto', v_categoria,
         (c ->> 'embedding')::extensions.vector, p_modelo
  from jsonb_array_elements(p_chunks) as c;
  return v_id;
end $$;

create or replace function public.atualizar_memoria(
  p_id uuid, p_texto text, p_categoria text, p_data_evento text,
  p_chunks jsonb default null, p_modelo text default 'gemini-embedding-001'
)
returns boolean language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_categoria text := public.normalizar_categoria(p_categoria);
begin
  insert into public.categorias (nome) values (v_categoria) on conflict do nothing;
  update public.memorias
     set texto = p_texto, categoria = v_categoria, data_evento = nullif(trim(p_data_evento), '')
   where id = p_id;
  if not found then
    return false;
  end if;
  if p_chunks is not null then
    delete from public.chunks where memoria_id = p_id;
    insert into public.chunks (memoria_id, indice, texto, categoria, embedding, modelo_embedding)
    select p_id, (c ->> 'indice')::int, c ->> 'texto', v_categoria,
           (c ->> 'embedding')::extensions.vector, p_modelo
    from jsonb_array_elements(p_chunks) as c;
  else
    update public.chunks set categoria = v_categoria where memoria_id = p_id;
  end if;
  return true;
end $$;

create or replace function public.renomear_categoria(p_antigo text, p_novo text)
returns void language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_antigo text := public.normalizar_categoria(p_antigo);
  v_novo   text := public.normalizar_categoria(p_novo);
begin
  if v_antigo = v_novo then return; end if;
  if not exists (select 1 from public.categorias where nome = v_antigo) then
    raise exception 'Categoria "%" não encontrada', v_antigo;
  end if;
  insert into public.categorias (nome) values (v_novo) on conflict do nothing;
  update public.memorias set categoria = v_novo where categoria = v_antigo;
  update public.chunks   set categoria = v_novo where categoria = v_antigo;
  delete from public.categorias where nome = v_antigo;
end $$;

create or replace function public.apagar_categoria(p_nome text, p_mover_para text default 'geral')
returns bigint language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_nome    text := public.normalizar_categoria(p_nome);
  v_destino text := public.normalizar_categoria(p_mover_para);
  v_movidas bigint;
begin
  if v_nome = v_destino then
    raise exception 'Escolha outra categoria para receber as memórias';
  end if;
  insert into public.categorias (nome) values (v_destino) on conflict do nothing;
  update public.memorias set categoria = v_destino where categoria = v_nome;
  get diagnostics v_movidas = row_count;
  update public.chunks set categoria = v_destino where categoria = v_nome;
  delete from public.categorias where nome = v_nome;
  return v_movidas;
end $$;

revoke execute on function public.listar_categorias, public.salvar_memoria, public.atualizar_memoria,
                           public.renomear_categoria, public.apagar_categoria from public, anon;
grant  execute on function public.listar_categorias, public.salvar_memoria, public.atualizar_memoria,
                           public.renomear_categoria, public.apagar_categoria to authenticated;

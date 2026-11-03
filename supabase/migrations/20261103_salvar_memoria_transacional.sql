-- Salva memória + chunks numa única transação: ou grava tudo, ou nada (sem memórias "órfãs").
-- SECURITY INVOKER: roda com o crachá de quem chamou, então o RLS continua valendo.
create or replace function public.salvar_memoria(
  p_texto       text,
  p_categoria   text,
  p_data_evento text,
  p_chunks      jsonb   -- [{"indice": 0, "texto": "...", "embedding": "[0.1, ...]"}, ...]
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

  insert into public.chunks (memoria_id, indice, texto, categoria, embedding)
  select v_id, (c ->> 'indice')::int, c ->> 'texto', v_categoria, (c ->> 'embedding')::extensions.vector
  from jsonb_array_elements(p_chunks) as c;

  return v_id;
end $$;
revoke execute on function public.salvar_memoria from public, anon;
grant  execute on function public.salvar_memoria to authenticated;

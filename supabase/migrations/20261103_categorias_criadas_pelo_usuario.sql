-- 1) A lista de categorias também mostra as que estão em uso nas memórias.
create or replace function public.listar_categorias()
returns table (nome text, memorias bigint)
language sql stable security invoker set search_path = '' as $$
  with nomes as (
    select nome from public.categorias
    union
    select distinct categoria from public.memorias
  )
  select n.nome, (select count(*) from public.memorias m where m.categoria = n.nome)
  from nomes n
  order by n.nome = 'geral' desc, n.nome;
$$;

-- 2) Pedido do dono: cada pessoa cria as próprias categorias (nada pré-definido).
drop trigger if exists categorias_padrao on auth.users;

-- 3) Remove as categorias padrão sem nenhuma memória (as criadas pelo usuário ficam).
delete from public.categorias c
where c.nome in ('geral','família','finanças','compromissos','trabalho','saúde','viagens','estudos','gostos')
  and not exists (select 1 from public.memorias m where m.user_id = c.user_id and m.categoria = c.nome);

-- LGPD (art. 18, VI): a pessoa pode apagar a própria conta. Todas as tabelas do app apontam para
-- auth.users com ON DELETE CASCADE, então apagar o usuário apaga memórias, chunks, categorias,
-- ajustes, avaliações e vínculo do WhatsApp juntos.
-- SECURITY DEFINER porque o usuário não pode mexer em auth.users; a função só apaga auth.uid(),
-- ou seja, quem está chamando — nunca outra conta. A senha é conferida antes, na API.
create function public.apagar_minha_conta()
returns void
language plpgsql security definer set search_path = ''
as $$
declare
  uid uuid := auth.uid();
begin
  if uid is null then
    raise exception 'login necessário';
  end if;
  delete from auth.users where id = uid;
end $$;

revoke execute on function public.apagar_minha_conta() from public, anon;
grant  execute on function public.apagar_minha_conta() to authenticated;

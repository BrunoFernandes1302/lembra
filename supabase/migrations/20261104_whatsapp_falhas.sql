-- Falhas de entrega informadas pela Meta (aviso de status "failed"). Só código e motivo:
-- sem conteúdo de mensagem nem número. Serve para diagnosticar por que uma resposta não chegou.
create table public.whatsapp_falhas (
  id        bigint generated always as identity primary key,
  codigo    int,
  titulo    text check (length(titulo) <= 300),
  detalhe   text check (length(detalhe) <= 600),
  quando    timestamptz not null default now()
);
alter table public.whatsapp_falhas enable row level security;

create function public.whatsapp_registrar_falha(p_codigo int, p_titulo text, p_detalhe text)
returns void
language sql security definer set search_path = ''
as $$
  delete from public.whatsapp_falhas where quando < now() - interval '30 days';
  insert into public.whatsapp_falhas (codigo, titulo, detalhe) values (p_codigo, left(p_titulo, 300), left(p_detalhe, 600));
$$;
revoke execute on function public.whatsapp_registrar_falha(int, text, text) from public, anon, authenticated;
grant  execute on function public.whatsapp_registrar_falha(int, text, text) to service_role;

-- Lembra no WhatsApp (API oficial da Meta). O bot não tem o login do usuário: ele recebe só
-- "o número X mandou Y". Estas tabelas ligam número ↔ conta com segurança.

-- Vínculo: um número por conta e um dono por número.
create table public.whatsapp_vinculos (
  user_id   uuid primary key default auth.uid() references auth.users (id) on delete cascade,
  telefone  text not null unique check (telefone ~ '^[0-9]{8,15}$'),
  criado_em timestamptz not null default now()
);
alter table public.whatsapp_vinculos enable row level security;
create policy "dono ve seu vinculo"    on public.whatsapp_vinculos for select to authenticated using ((select auth.uid()) = user_id);
create policy "dono apaga seu vinculo" on public.whatsapp_vinculos for delete to authenticated using ((select auth.uid()) = user_id);

-- Códigos de vínculo (curtos, de uso único). Sem políticas: só as funções abaixo tocam aqui.
create table public.whatsapp_codigos (
  user_id   uuid primary key references auth.users (id) on delete cascade,
  codigo    text not null unique,
  expira_em timestamptz not null
);
alter table public.whatsapp_codigos enable row level security;

-- Tentativas erradas de vínculo (limite contra adivinhação de código).
create table public.whatsapp_tentativas (
  id       bigint generated always as identity primary key,
  telefone text not null,
  quando   timestamptz not null default now()
);
alter table public.whatsapp_tentativas enable row level security;
create index whatsapp_tentativas_idx on public.whatsapp_tentativas (telefone, quando desc);

-- Idempotência: a Meta pode entregar a MESMA mensagem mais de uma vez (reenvio após timeout).
create table public.whatsapp_processadas (
  mensagem_id text primary key,
  recebida_em timestamptz not null default now()
);
alter table public.whatsapp_processadas enable row level security;

-- Usuário logado (no app) gera seu código. 8 caracteres de um alfabeto de 32 símbolos sem
-- ambíguos: 256 % 32 = 0, então cada byte aleatório vira um símbolo sem viés.
create function public.whatsapp_gerar_codigo()
returns text
language plpgsql security definer set search_path = ''
as $$
declare
  uid uuid := auth.uid();
  alfabeto constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  bytes bytea := extensions.gen_random_bytes(8);
  codigo text := '';
begin
  if uid is null then
    raise exception 'login necessário';
  end if;
  for i in 0..7 loop
    codigo := codigo || substr(alfabeto, (get_byte(bytes, i) % 32) + 1, 1);
  end loop;
  insert into public.whatsapp_codigos (user_id, codigo, expira_em)
  values (uid, codigo, now() + interval '10 minutes')
  on conflict (user_id) do update set codigo = excluded.codigo, expira_em = excluded.expira_em;
  return codigo;
end $$;

-- Bot: quem é o dono deste número?
create function public.whatsapp_dono(p_telefone text)
returns uuid
language sql stable security definer set search_path = ''
as $$ select user_id from public.whatsapp_vinculos where telefone = p_telefone $$;

-- Bot: "VINCULAR ABCD2345" vindo do número p_telefone. Retorna o dono, ou null se o código não vale.
create function public.whatsapp_vincular(p_codigo text, p_telefone text)
returns uuid
language plpgsql security definer set search_path = ''
as $$
declare
  dono uuid;
begin
  if (select count(*) from public.whatsapp_tentativas
      where telefone = p_telefone and quando > now() - interval '1 hour') >= 5 then
    raise exception 'muitas tentativas; aguarde uma hora';
  end if;
  delete from public.whatsapp_codigos
   where codigo = upper(trim(p_codigo)) and expira_em > now()
  returning user_id into dono;  -- apagar ao usar = uso único
  if dono is null then
    insert into public.whatsapp_tentativas (telefone) values (p_telefone);
    return null;
  end if;
  delete from public.whatsapp_vinculos where telefone = p_telefone;  -- o número muda de conta
  insert into public.whatsapp_vinculos (user_id, telefone) values (dono, p_telefone)
  on conflict (user_id) do update set telefone = excluded.telefone, criado_em = now();
  return dono;
end $$;

-- Bot: true na 1ª vez que vê a mensagem; false se for reenvio (já processada).
create function public.whatsapp_marcar_processada(p_id text)
returns boolean
language plpgsql security definer set search_path = ''
as $$
begin
  delete from public.whatsapp_processadas where recebida_em < now() - interval '7 days';
  insert into public.whatsapp_processadas (mensagem_id) values (p_id) on conflict do nothing;
  return found;
end $$;

-- Permissões: por padrão o Supabase libera funções novas para todos. Aqui, o mínimo necessário.
revoke execute on function public.whatsapp_gerar_codigo() from public, anon;
grant  execute on function public.whatsapp_gerar_codigo() to authenticated;
revoke execute on function public.whatsapp_dono(text), public.whatsapp_vincular(text, text),
                           public.whatsapp_marcar_processada(text) from public, anon, authenticated;
grant  execute on function public.whatsapp_dono(text), public.whatsapp_vincular(text, text),
                           public.whatsapp_marcar_processada(text) to service_role;

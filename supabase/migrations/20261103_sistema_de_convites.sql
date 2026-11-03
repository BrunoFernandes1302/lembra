-- Sistema de convites do Lembra. Cadastro só com código válido, validado NO BANCO (trigger),
-- então não dá para contornar chamando a API direto. Explicação: docs/conceitos.md.

-- ADMINISTRADORES: quem pode gerar convites
create table public.admins (
  user_id   uuid primary key references auth.users (id) on delete cascade,
  criado_em timestamptz not null default now()
);
alter table public.admins enable row level security;
create policy "admin ve a si mesmo" on public.admins for select to authenticated
  using ((select auth.uid()) = user_id);

-- CONVITES: cada código vale uma vez, tem validade e pode ser preso a um e-mail
create table public.convites (
  id           uuid primary key default gen_random_uuid(),
  codigo       text not null unique,
  email        text,                                   -- se preenchido, só esse e-mail pode usar
  torna_admin  boolean not null default false,
  criado_por   uuid references auth.users (id) on delete set null,
  criado_em    timestamptz not null default now(),
  expira_em    timestamptz not null default now() + interval '14 days',
  usado_por    uuid references auth.users (id) on delete set null,
  usado_em     timestamptz
);
alter table public.convites enable row level security;
-- Admin vê os convites que criou. Ninguém insere/altera direto: só pelas funções abaixo.
create policy "admin ve seus convites" on public.convites for select to authenticated
  using (criado_por = (select auth.uid()));

-- Gera um código legível, sem caracteres ambíguos (0/O, 1/I/L)
create or replace function public.gerar_codigo_convite()
returns text language plpgsql volatile set search_path = '' as $$
declare
  alfabeto constant text := 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';
  bytes bytea := extensions.gen_random_bytes(10);
  codigo text := '';
begin
  for i in 0..9 loop
    codigo := codigo || substr(alfabeto, (get_byte(bytes, i) % length(alfabeto)) + 1, 1);
    if i = 4 then codigo := codigo || '-'; end if;
  end loop;
  return codigo;
end $$;
revoke execute on function public.gerar_codigo_convite from public, anon, authenticated;

-- Admin cria convite pelo app: criar_convite('amigo@email.com') ou criar_convite().
-- SECURITY DEFINER de propósito (o linter avisa): é a ÚNICA porta para criar convites,
-- e a primeira coisa que faz é exigir que quem chamou seja admin.
create or replace function public.criar_convite(email_convidado text default null, dias int default 14)
returns text language plpgsql volatile security definer set search_path = '' as $$
declare novo_codigo text;
begin
  if not exists (select 1 from public.admins where user_id = (select auth.uid())) then
    raise exception 'Apenas administradores podem criar convites';
  end if;
  insert into public.convites (codigo, email, criado_por, expira_em)
  values (public.gerar_codigo_convite(), lower(trim(email_convidado)), (select auth.uid()),
          now() + make_interval(days => least(greatest(dias, 1), 90)))
  returning codigo into novo_codigo;
  return novo_codigo;
end $$;
revoke execute on function public.criar_convite from public, anon;
grant  execute on function public.criar_convite to authenticated;

-- A TRAVA: roda dentro do cadastro; se o convite não for válido, o cadastro é cancelado.
create or replace function public.exigir_convite_no_cadastro()
returns trigger language plpgsql security definer set search_path = '' as $$
declare
  c public.convites;
  codigo_enviado text := upper(trim(coalesce(new.raw_user_meta_data ->> 'convite', '')));
begin
  if codigo_enviado = '' then
    raise exception 'Cadastro exige código de convite';
  end if;

  -- FOR UPDATE trava a linha: dois cadastros simultâneos não conseguem usar o mesmo código
  select * into c from public.convites where codigo = codigo_enviado for update;

  if not found                then raise exception 'Convite inválido'; end if;
  if c.usado_em is not null   then raise exception 'Convite já utilizado'; end if;
  if c.expira_em < now()      then raise exception 'Convite expirado'; end if;
  if c.email is not null and c.email <> lower(new.email) then
    raise exception 'Este convite é para outro e-mail';
  end if;

  update public.convites set usado_por = new.id, usado_em = now() where id = c.id;
  if c.torna_admin then
    insert into public.admins (user_id) values (new.id);
  end if;
  return new;
end $$;
revoke execute on function public.exigir_convite_no_cadastro from public, anon, authenticated;

create trigger exigir_convite
  after insert on auth.users
  for each row execute function public.exigir_convite_no_cadastro();

-- Cadastro livre: cada testador cria a própria conta, sem código de convite.
-- A trava é só desligada; tabelas e funções de convite ficam guardadas para religar se preciso:
--   create trigger exigir_convite after insert on auth.users
--     for each row execute function public.exigir_convite_no_cadastro();
drop trigger if exists exigir_convite on auth.users;

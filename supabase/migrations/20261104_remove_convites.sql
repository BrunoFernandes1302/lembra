-- O cadastro é livre (decisão do produto): a trava de convites não volta.
-- Remove as sobras: o verificador de segurança apontou que qualquer usuário logado ainda podia
-- chamar criar_convite (SECURITY DEFINER), e nenhuma parte do app usa estas peças.
drop function if exists public.criar_convite(text, integer);
drop function if exists public.gerar_codigo_convite();
drop function if exists public.exigir_convite_no_cadastro();
drop table if exists public.convites;

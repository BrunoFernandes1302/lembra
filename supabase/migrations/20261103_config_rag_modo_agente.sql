-- Modo agente (experimental): o LLM usa ferramentas. Desligado por padrão (mais lento e gasta mais cota).
alter table public.config_rag add column modo_agente boolean not null default false;

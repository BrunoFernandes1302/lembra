"""Publica o Lembra no Hugging Face Spaces (API + app no mesmo endereço).

Uso:
    HF_TOKEN=hf_...  GEMINI_API_KEY=...  python scripts/publicar_hf.py usuario/lembra

O que faz:
  1. Cria o Space (tipo Docker) se ainda não existir.
  2. Cadastra as configurações: SECRETAS (escondidas) e VARIÁVEIS (visíveis).
  3. Envia só os arquivos que o servidor precisa; o HF lê o Dockerfile e monta o servidor.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from huggingface_hub import HfApi

RAIZ = Path(__file__).resolve().parents[1]
ARQUIVOS = ["Dockerfile", ".dockerignore", "pyproject.toml"]
PASTAS = ["src", "web"]

# O README de um Space precisa deste cabeçalho para o HF saber que é um app Docker na porta 7860.
README_SPACE = """---
title: Lembra
emoji: 🧠
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
short_description: Assistente de vida pessoal com IA (RAG)
---

# Lembra

App de organização da vida pessoal com IA. Acesso somente com convite.
Código-fonte e documentação: repositório privado do projeto.
"""

VARIAVEIS = {
    "SUPABASE_URL": "https://xxikbkdtyswcpsaqtmjg.supabase.co",
    # Chave "publishable": pública por design; a segurança vem do login + RLS.
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_Cz5KoK2lFsX3Li89GnZz-A_1QFPziyS",
    "LLM_PROVIDER": "gemini",
    "GEMINI_MODEL": "gemini-flash-lite-latest",
}
SECRETOS = ["GEMINI_API_KEY"]  # lidos do ambiente, nunca escritos em arquivo


def main(repo_id: str) -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Defina HF_TOKEN (token de escrita do Hugging Face).")
    api = HfApi(token=token)

    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    print(f"Space pronto: https://huggingface.co/spaces/{repo_id}")

    for nome, valor in VARIAVEIS.items():
        api.add_space_variable(repo_id, nome, valor)
    for nome in SECRETOS:
        if os.environ.get(nome):
            api.add_space_secret(repo_id, nome, os.environ[nome])
            print(f"Segredo {nome} cadastrado")
        else:
            print(f"Aviso: {nome} não definido; mantendo o valor que já estiver no Space")

    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp)
        for arq in ARQUIVOS:
            shutil.copy2(RAIZ / arq, destino / arq)
        for pasta in PASTAS:
            shutil.copytree(RAIZ / pasta, destino / pasta,
                            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
        (destino / "README.md").write_text(README_SPACE, encoding="utf-8")
        api.upload_folder(folder_path=destino, repo_id=repo_id, repo_type="space",
                          commit_message="Publica o Lembra", delete_patterns="*")
    print("Arquivos enviados. O Hugging Face vai montar o servidor (leva alguns minutos).")
    print(f"App: https://{repo_id.replace('/', '-').lower()}.hf.space")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

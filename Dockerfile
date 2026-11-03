# Receita do servidor do Lembra (API + app). Usada pelo Hugging Face Spaces.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/user/.cache/huggingface \
    LEMBRA_WEB_DIR=/home/user/app/web

# O Hugging Face roda o container com o usuário de id 1000 (não-root, mais seguro)
RUN useradd -m -u 1000 user
USER user
ENV PATH=/home/user/.local/bin:$PATH
WORKDIR /home/user/app

# 1) PyTorch só-CPU (o servidor grátis não tem GPU; a versão CPU é bem menor)
RUN pip install --user --index-url https://download.pytorch.org/whl/cpu torch

# 2) O Lembra e suas dependências
COPY --chown=user pyproject.toml README.md ./
COPY --chown=user src ./src
RUN pip install --user .

# 3) Baixa o modelo de embeddings AGORA, na montagem, e não no primeiro uso
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

# 4) O app (PWA)
COPY --chown=user web ./web

EXPOSE 7860
CMD ["uvicorn", "lembra.api:app", "--host", "0.0.0.0", "--port", "7860"]

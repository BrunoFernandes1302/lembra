# Receita para rodar o Lembra em qualquer servidor com Docker (alternativa à Vercel).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 LEMBRA_WEB_DIR=/app/web
RUN useradd -m -u 1000 lembra
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .
COPY web ./web
USER lembra
EXPOSE 8000
CMD ["uvicorn", "lembra.api:app", "--host", "0.0.0.0", "--port", "8000"]

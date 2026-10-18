# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) Configuration + code du paquet (pour un cache Docker efficace)
COPY pyproject.toml ./
COPY yt_veille ./yt_veille
RUN pip install --upgrade pip && pip install .

# 2) Reste du projet (seed.yml, etc.)
COPY . .

EXPOSE 8000

# Crée les tables, importe les domaines (idempotent), puis lance l'interface web.
# ${PORT} est fourni par l'hébergeur (Render, etc.). En local, défaut 8000.
CMD ["sh", "-c", "yt-veille init-db && yt-veille seed && yt-veille serve --host 0.0.0.0 --port ${PORT:-8000}"]

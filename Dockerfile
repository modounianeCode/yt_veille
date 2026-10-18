# syntax=docker/dockerfile:1

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Installe d'abord les dépendances (cache Docker plus efficace)
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

# Puis le code
COPY . .

# Crée les tables au démarrage et affiche l'aide
CMD ["sh", "-c", "yt-veille init-db && yt-veille domains"]

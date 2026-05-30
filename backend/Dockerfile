# ============================================================
# SIGMA Backend — Dockerfile
# ============================================================
# Build  : docker build -t sigma-backend .
# Run    : docker run -p 8000:8000 --env-file .env sigma-backend
# ============================================================

# --- Stage 1 : Image de base légère ---
FROM python:3.12-slim AS base

# Métadonnées OCI
LABEL org.opencontainers.image.title="SIGMA Backend API"
LABEL org.opencontainers.image.description="API FastAPI pour le système SIGMA"
LABEL org.opencontainers.image.version="1.0.0"

# Variables d'environnement Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dépendances système (build tools pour bcrypt/psycopg2)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*


# --- Stage 2 : Installation des dépendances ---
FROM base AS deps

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt


# --- Stage 3 : Image de production ---
FROM deps AS production

# Copier le code source
COPY app/ ./app/

# Utilisateur non-root (sécurité)
RUN addgroup --system sigma && \
    adduser --system --ingroup sigma --no-create-home sigma_user
USER sigma_user

# Port exposé
EXPOSE 8000

# Health check Docker
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Démarrage de l'application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

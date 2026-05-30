"""
SIGMA Backend — Point d'entrée ASGI pour production.

Utilisé par uvicorn et les serveurs ASGI :
    uvicorn asgi:app --host 0.0.0.0 --port 8000

Ou via Dockerfile/Gunicorn :
    gunicorn asgi:app -k uvicorn.workers.UvicornWorker
"""
from app.main import app  # noqa: F401 — exposition de l'objet ASGI

__all__ = ["app"]

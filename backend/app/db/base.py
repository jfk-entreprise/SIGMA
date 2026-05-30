"""Base déclarative SQLAlchemy partagée par tous les modèles SIGMA."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

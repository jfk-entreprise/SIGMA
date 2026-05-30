"""
Registre des modèles SQLAlchemy SIGMA.
Importer ce module garantit que tous les modèles sont chargés
avant tout appel à Base.metadata.create_all().
"""
from app.models.user import User  # noqa: F401
from app.models.business import Business, BusinessUser  # noqa: F401
from app.models.item import ItemDefinition, BusinessItem  # noqa: F401
from app.models.service_order import ServiceOrder, ServiceOrderItem  # noqa: F401
from app.models.financial import Payment, Expense, Credit  # noqa: F401

__all__ = [
    "User",
    "Business",
    "BusinessUser",
    "ItemDefinition",
    "BusinessItem",
    "ServiceOrder",
    "ServiceOrderItem",
    "Payment",
    "Expense",
    "Credit",
]

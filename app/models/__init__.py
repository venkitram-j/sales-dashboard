"""Import every model module here so Base.metadata is fully populated for
Alembic's --autogenerate to see all tables."""
from app.models.app_setting import AppSetting
from app.models.ingested_file import IngestedFile
from app.models.product_supplier_lead_time import ProductSupplierLeadTime
from app.models.sales_fact import SalesFact
from app.models.user import User
from app.models.user_session import UserSession

__all__ = [
    "AppSetting",
    "IngestedFile",
    "ProductSupplierLeadTime",
    "SalesFact",
    "User",
    "UserSession",
]

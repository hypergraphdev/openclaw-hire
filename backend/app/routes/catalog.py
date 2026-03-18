from __future__ import annotations

from fastapi import APIRouter

from ..schemas import PRODUCTS, ProductCatalog

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("", response_model=list[ProductCatalog])
def list_products() -> list[ProductCatalog]:
    return PRODUCTS

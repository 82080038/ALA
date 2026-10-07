"""
Router API v1 — menggabungkan semua modul endpoint.
"""
from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.endpoints import router as endpoints_router

router = APIRouter()
router.include_router(endpoints_router, tags=["core"])
router.include_router(admin_router)

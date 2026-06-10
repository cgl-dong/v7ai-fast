"""API router for version 1 endpoints."""
from fastapi import APIRouter

from app.api.v1.endpoints import woa, web

api_router = APIRouter()
api_router.include_router(woa.router, tags=["woa"])
api_router.include_router(web.router, tags=["web"])

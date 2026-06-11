"""API router for version 1 endpoints."""
from fastapi import APIRouter

from app.api.v1.endpoints import woa, auth, model

api_router = APIRouter()
api_router.include_router(woa.router, tags=["woa"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(model.router, prefix="/model", tags=["model"])

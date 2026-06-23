"""API router for version 1 endpoints."""
from fastapi import APIRouter

from app.api.v1.endpoints import woa, auth, model, knowledge, prompt, observability, skills

api_router = APIRouter()
api_router.include_router(woa.router, tags=["woa"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(model.router, prefix="/model", tags=["model"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(prompt.router, prefix="/prompt", tags=["prompt"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])

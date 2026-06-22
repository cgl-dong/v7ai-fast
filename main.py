"""v7ai-fast - FastAPI based WOA smart assistant backend."""
import os
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api import api_router
from app.core.settings import settings
from app.core.logging import logger
from app.api.v1.endpoints.woa import router as woa_router
from app.api.v1.endpoints.web import router as web_router

logger.info("v7ai-fast service starting...")

app = FastAPI(
    title="v7ai-fast",
    description="WOA Smart Assistant Backend Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(api_router)
app.include_router(woa_router, prefix="")
app.include_router(web_router, prefix="")


@app.on_event("startup")
async def startup_event():
    """Preload heavy models at startup to avoid first-request latency."""
    async def _preload():
        try:
            from app.services.embedding import get_embedding_model
            model = await asyncio.to_thread(get_embedding_model)
            logger.info(f"Embedding model preloaded: dim={model.get_sentence_embedding_dimension()}")
        except Exception as e:
            logger.warning(f"Failed to preload embedding model (will lazy-load on first use): {e}")
    asyncio.create_task(_preload())


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "v7ai-fast"}


@app.get("/v7")
async def index():
    """Redirect to static index page."""
    from starlette.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=settings.server_port, reload=True)

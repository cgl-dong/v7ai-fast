import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from app.controllers.callback_controller import router as callback_router
from app.controllers.index_controller import router as index_router

load_dotenv()

app = FastAPI(title="v7ai-fast", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(callback_router)
app.include_router(index_router)


@app.get("/")
async def root():
    return {"message": "v7ai-fast API is running"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SERVER_PORT", 18081))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)

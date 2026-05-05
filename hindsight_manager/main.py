from contextlib import asynccontextmanager

from fastapi import FastAPI

from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Hindsight Manager", lifespan=lifespan)
app.include_router(auth_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

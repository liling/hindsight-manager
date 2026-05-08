from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from hindsight_manager.api.api_keys import router as api_keys_router
from hindsight_manager.api.auth import router as auth_router
from hindsight_manager.api.members import router as members_router
from hindsight_manager.api.proxy import router as proxy_router
from hindsight_manager.api.tenants import router as tenants_router
from hindsight_manager.config import Settings
from hindsight_manager.db import init_db

settings = Settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(settings)
    yield


app = FastAPI(title="Hindsight Manager", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://cp.local.mem99.cn:3001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(tenants_router)
app.include_router(members_router)
app.include_router(api_keys_router)
app.include_router(proxy_router)


@app.get("/health")
async def health():
    return {"status": "ok"}

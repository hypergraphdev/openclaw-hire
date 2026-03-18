from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import init_db
from .routes.auth import router as auth_router
from .routes.catalog import router as catalog_router
from .routes.instances import router as instances_router

app = FastAPI(title="OpenClaw Hire API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(instances_router)

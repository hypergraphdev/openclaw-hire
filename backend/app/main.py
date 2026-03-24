from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import asyncio

from .database import init_db, DB_PATH
from .routes.auth import router as auth_router
from .routes.catalog import router as catalog_router
from .routes.instances import router as instances_router
from .routes import admin_settings, admin_hxa, my_org, metrics
from .routes.admin import router as admin_router

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
    # Start background metrics collector
    from .services.metrics_collector import collect_loop
    asyncio.get_event_loop().create_task(collect_loop(str(DB_PATH)))


@app.get("/api/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "version": "1.0.0"}


app.include_router(auth_router)
app.include_router(catalog_router)
app.include_router(instances_router)
app.include_router(admin_router)
app.include_router(admin_settings.router)
app.include_router(admin_hxa.router)
app.include_router(my_org.router)
app.include_router(metrics.router)

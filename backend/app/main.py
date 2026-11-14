"""FastAPI application: Reviews Dekho AI backend.

Run from the backend/ folder:
    .venv/bin/uvicorn app.main:app --reload
Interactive API docs (Swagger): http://localhost:8000/docs
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import config
from .api import ai, health, history, products, reviews, sites, uploads
from .database import init_db
from .errors import register_error_handlers

logging.basicConfig(level=logging.INFO)

DESCRIPTION = """
Analyse customer reviews from uploaded CSV / Excel files, or collected from
product links on supported websites (currently the Apple App Store).

**Upload flow:** `POST /api/uploads/preview` → check the detected columns →
`POST /api/uploads/import` → `GET /api/products/{id}/analysis`.

**Link flow:** `POST /api/products/from-url` → `GET /api/products/{id}/analysis`.
`GET /api/sites` lists which websites are recognised and which can be collected.

Sentiment is rule-based (VADER), features come from a keyword list, and
summaries are built from the computed numbers — nothing is invented.
All errors return `{"detail": "<readable message>"}`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Reviews Dekho AI API", version="0.4.0", description=DESCRIPTION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )
    register_error_handlers(app)
    for module in (health, products, reviews, uploads, history, sites, ai):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()

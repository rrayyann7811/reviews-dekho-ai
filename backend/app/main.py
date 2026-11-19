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
from .auth import AuthMiddleware, TokenVerifier
from .api import ai, compare, health, history, jobs, products, reviews, sites, uploads
from .database import init_db
from .errors import register_error_handlers
from .version import VERSION
from .resource_limits import ResourceLimitsMiddleware
from .rate_limits import RateLimitsMiddleware

logging.basicConfig(level=logging.INFO)

DESCRIPTION = """
Analyse customer reviews from uploaded CSV / Excel files, or collected from
product links on supported websites (currently the Apple App Store).

**Upload flow:** `POST /api/uploads/preview` → check the detected columns →
`POST /api/uploads/import` → `GET /api/products/{id}/analysis`.

**Link flow:** `POST /api/products/from-url` → `GET /api/products/{id}/analysis`.
`GET /api/sites` lists which websites are recognised and which can be collected.

**Sentiment:** a pretrained model (Twitter-RoBERTa, Cardiff NLP) when its files are installed, otherwise VADER
(rule-based); every run records which one it used. Only English is analysed: reviews in other languages (e.g. Hindi or
Hinglish) are marked "not analysed" and left out of the sentiment figures. Features come from keyword lists, and
summaries are built only from the computed numbers and exact review excerpts — nothing is invented.

**Reports:** `GET /api/products/{id}/report.pdf` and `report.csv` for any stored run (`analysis_id`); reviewer names are
left out unless `include_reviewer=true` is added to the CSV request.

**Comparison:** `GET /api/compare` puts two stored runs side by side (two products, or two runs of one product) with 95%
intervals and sample-size caveats.

**Optional AI overview:** off unless the server is started with `AI_SUMMARIES=on`; uses a local Ollama model only, and
a checker rejects detectable errors (wrong numbers, invented quotes) but can't guarantee accuracy
(`GET /api/ai/status`).

All errors return `{"detail": "<readable message>"}`.
"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    if config.AUTH_MODE not in {"local", "jwt"}:
        raise ValueError("AUTH_MODE must be local or jwt")
    verifier = TokenVerifier() if config.AUTH_MODE == "jwt" else None
    app = FastAPI(title="Reviews Dekho AI API", version=VERSION, description=DESCRIPTION, lifespan=lifespan)
    app.add_middleware(ResourceLimitsMiddleware)
    app.add_middleware(RateLimitsMiddleware, phase="owner")
    app.add_middleware(AuthMiddleware, mode=config.AUTH_MODE, verifier=verifier)
    app.add_middleware(RateLimitsMiddleware, phase="peer")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Idempotency-Key"],
        expose_headers=["Content-Disposition", "Retry-After"],
    )
    register_error_handlers(app)
    for module in (health, products, reviews, uploads, history, sites, ai, compare, jobs):
        app.include_router(module.router, prefix="/api")
    return app


app = create_app()

"""Hosted-only admission and request error handling."""

import logging

from fastapi import HTTPException
from sqlalchemy import text
from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse

from . import config

log = logging.getLogger("reviews_dekho")
# Separate from the Alembic migration lock and existing product/job locks.
EXPENSIVE_LOCK = 829314202


def admit_expensive_work(db):
    """Serialize analysis and exports across instances using the request's transaction."""
    if not config.PUBLIC_DEMO:
        return
    if db.get_bind().dialect.name != "postgresql":
        raise HTTPException(503, "Hosted request protection is unavailable.")
    if not db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": EXPENSIVE_LOCK}):
        raise HTTPException(429, "The showcase is busy. Please try again shortly.", headers={"Retry-After": "5"})


class HostedErrorMiddleware:
    """Keep exception values and traceback locals out of hosted request logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_response(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if scope["path"].startswith("/api/"):
                    MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            await send(message)

        try:
            await self.app(scope, receive, send_response)
        except Exception as error:
            log.error("Hosted request failed (%s)", type(error).__name__)
            if started:
                raise RuntimeError("Hosted response interrupted") from None
            await JSONResponse(
                {"detail": "Something went wrong on the server. Please try again."}, status_code=500,
            )(scope, receive, send_response)

"""Consistent error responses: every error body is {"detail": "<readable message>"}.

The frontend shows `detail` directly to the user, so messages are written in
plain language.
"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("reviews_dekho")


class AppError(Exception):
    """Raise from services for expected problems the user can fix."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class NotFound(AppError):
    def __init__(self, message: str):
        super().__init__(message, 404)


def _describe(error: dict) -> str:
    where = ".".join(str(p) for p in error.get("loc", ()) if p not in ("body", "query", "path", "form"))
    return f"{where}: {error.get('msg')}" if where else str(error.get("msg"))


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errors = [{"field": _describe(e).split(":")[0], "message": e.get("msg")} for e in exc.errors()]
        message = "Some of the information sent is invalid: " + "; ".join(_describe(e) for e in exc.errors())
        return JSONResponse({"detail": message, "errors": errors}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        if exc.status_code == 404 and detail == "Not Found":
            detail = "This address doesn’t exist on the API."
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unexpected_error(_: Request, exc: Exception):
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Something went wrong on the server. Please try again."}, status_code=500)

import hashlib
import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile, status
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import config
from ..upload_route import UploadRoute
from ..database import get_db
from ..errors import AppError
from ..models import Product
from ..schemas import ColumnMap, ErrorResponse, ProductSummary, UploadPreview
from ..services import analysis as analysis_service
from ..services import import_receipts, ingestion
from ..services import products as product_service
from ..services.ownership import new_product_identity, principal

router = APIRouter(prefix="/uploads", tags=["Uploads"], route_class=UploadRoute)
FILE_ERRORS = {
    400: {"model": ErrorResponse, "description": "The file couldn’t be read"},
    413: {"model": ErrorResponse, "description": "File too large or too many rows"},
    415: {"model": ErrorResponse, "description": "Not a CSV or .xlsx file"},
}


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    try:
        content = await file.read(config.MAX_UPLOAD_BYTES + 1)
        return ingestion.check_file(file.filename, content), content
    finally:
        await file.close()


@router.get("/limits")
def upload_limits():
    return {"maxRows": config.MAX_ROWS, "maxReviewChars": config.MAX_REVIEW_CHARS,
            "maxUploadBytes": config.MAX_UPLOAD_BYTES, "maxRequestBytes": config.MAX_REQUEST_BYTES}


@router.get("/import-status/{key}", response_model=ProductSummary)
def import_status(key: str, response: Response, db: Session = Depends(get_db)):
    if principal(db).local:
        raise AppError("Import status requires an authenticated account.", 404)
    response.headers["Cache-Control"] = "no-store"
    return import_receipts.status_result(db, key)


@router.post("/preview", response_model=UploadPreview, responses=FILE_ERRORS,
             summary="Read a file and suggest which column holds each field (nothing is saved)")
async def preview_upload(file: UploadFile = File(..., description="CSV or .xlsx; size limits are configured by the server")):
    name, content = await _read_upload(file)
    def preview():
        return ingestion.build_preview(name, ingestion.read_table(name, content))
    return await run_in_threadpool(preview)


@router.post("/import", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             responses=FILE_ERRORS | {422: {"model": ErrorResponse, "description": "Invalid columns or no usable reviews"}},
             summary="Import a file as a new product and analyse its reviews")
async def import_upload(
    file: UploadFile = File(..., description="CSV or .xlsx; size limits are configured by the server"),
    product_name: str = Form(..., min_length=1, max_length=200),
    columns: str = Form(..., description='JSON, e.g. {"text": "Review", "rating": "Stars"}'),
    brand: str | None = Form(None, max_length=120),
    category: str | None = Form(None, max_length=120),
    domain: Literal["product", "app"] = Form("product", description="What is reviewed: a physical product or an app"),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None),
):
    try:
        column_map = ColumnMap.model_validate(json.loads(columns))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AppError("The column choices are invalid. The review text column is required.", 422) from exc
    if not product_name.strip():
        raise AppError("Enter a product name.", 422)

    key = None if principal(db).local else idempotency_key
    if config.PUBLIC_DEMO and key is None:
        raise AppError("An import key is required. Reload the upload page and try again.", 422)
    if key is not None:
        import_receipts.validate_key(key)
    name, content = await _read_upload(file)
    return await run_in_threadpool(_import_table, db, name, content, column_map, product_name, brand, category, domain, key)


def _import_table(db, name, content, column_map, product_name, brand, category, domain, key=None):
    columns = column_map.model_dump(by_alias=True)
    metadata = {"name": product_name.strip(), "brand": (brand or "").strip() or None,
                "category": (category or "").strip() or None, "domain": domain, "file_name": name}
    receipt = None
    if key is not None:
        options = json.dumps({"product": metadata, "columns": columns}, sort_keys=True).encode()
        fingerprint = hashlib.sha256(hashlib.sha256(content).digest() + options).hexdigest()
        receipt, replay = import_receipts.claim(db, key, fingerprint)
        if receipt is None:
            return replay

    df = ingestion.read_table(name, content)
    reviews, report = ingestion.clean_reviews(df, columns)
    product = Product(**new_product_identity(db), **metadata, source="upload")
    db.add(product)
    product_service.add_reviews(db, product, reviews)
    db.flush()
    analysis_service.run_analysis(db, product, ingestion=report | {"fileName": name})
    result = product_service.summary_out(product)
    if receipt is not None:
        receipt.product_id = product.id
        receipt.expires_at = product.expires_at
        receipt.result = ProductSummary.model_validate(result).model_dump(mode="json", by_alias=True)
    db.commit()
    return result

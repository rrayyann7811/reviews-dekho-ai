import json

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..errors import AppError
from ..models import Product
from ..schemas import ColumnMap, ErrorResponse, ProductSummary, UploadPreview
from ..services import analysis as analysis_service
from ..services import ingestion
from ..services import products as product_service

router = APIRouter(prefix="/uploads", tags=["Uploads"])
FILE_ERRORS = {
    400: {"model": ErrorResponse, "description": "The file couldn’t be read"},
    413: {"model": ErrorResponse, "description": "File too large or too many rows"},
    415: {"model": ErrorResponse, "description": "Not a CSV or .xlsx file"},
}


async def _read_upload(file: UploadFile) -> tuple[str, bytes]:
    content = await file.read(config.MAX_UPLOAD_BYTES + 1)  # never read more than the limit + 1 byte
    return ingestion.check_file(file.filename, content), content


@router.post("/preview", response_model=UploadPreview, responses=FILE_ERRORS,
             summary="Read a file and suggest which column holds each field (nothing is saved)")
async def preview_upload(file: UploadFile = File(..., description="CSV or .xlsx, max 10 MB")):
    name, content = await _read_upload(file)
    return ingestion.build_preview(name, ingestion.read_table(name, content))


@router.post("/import", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             responses=FILE_ERRORS | {422: {"model": ErrorResponse, "description": "Invalid columns or no usable reviews"}},
             summary="Import a file as a new product and analyse its reviews")
async def import_upload(
    file: UploadFile = File(..., description="CSV or .xlsx, max 10 MB"),
    product_name: str = Form(..., min_length=1, max_length=200),
    columns: str = Form(..., description='JSON, e.g. {"text": "Review", "rating": "Stars"}'),
    brand: str | None = Form(None, max_length=120),
    category: str | None = Form(None, max_length=120),
    db: Session = Depends(get_db),
):
    try:
        column_map = ColumnMap.model_validate(json.loads(columns))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise AppError("The column choices are invalid. The review text column is required.", 422) from exc
    if not product_name.strip():
        raise AppError("Enter a product name.", 422)

    name, content = await _read_upload(file)
    df = ingestion.read_table(name, content)
    reviews, report = ingestion.clean_reviews(df, column_map.model_dump(by_alias=True))

    product = Product(name=product_name.strip(), brand=(brand or "").strip() or None,
                      category=(category or "").strip() or None, source="upload", file_name=name)
    db.add(product)
    product_service.add_reviews(db, product, reviews)
    db.flush()
    analysis_service.run_analysis(db, product, ingestion=report | {"fileName": name})
    db.commit()
    return product_service.summary_out(product)

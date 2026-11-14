from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import AppError
from ..models import Product
from ..schemas import Analysis, ErrorResponse, ProductCreate, ProductSummary, ProductUpdate, UrlRequest
from ..services import analysis as analysis_service
from ..services import products as product_service
from ..reports.pdf import build_report
from ..services import collection, reports, review_query
from ..services.ownership import new_product_identity

router = APIRouter(prefix="/products", tags=["Products"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product not found"}}
NOT_ANALYSED = {409: {"model": ErrorResponse, "description": "The product hasn’t been analysed yet"}}


@router.get("", response_model=list[ProductSummary], summary="List all products, newest first")
def list_products(db: Session = Depends(get_db)):
    return [product_service.summary_out(p) for p in product_service.list_products(db)]


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             summary="Create an empty product (add reviews to it afterwards)")
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    product = Product(**new_product_identity(db), name=body.name, brand=body.brand, category=body.category,
                      domain=body.domain, source="manual")
    db.add(product)
    db.commit()
    return product_service.summary_out(product)


COLLECTION_ERRORS = {
    404: {"model": ErrorResponse, "description": "The product doesn’t exist on the website"},
    422: {"model": ErrorResponse, "description": "Invalid link, website not supported or not permitted, or no reviews"},
    502: {"model": ErrorResponse, "description": "The website couldn’t be reached or answered unexpectedly"},
    503: {"model": ErrorResponse, "description": "The website is rate-limiting requests"},
    504: {"model": ErrorResponse, "description": "The website took too long to respond"},
}


@router.post("/from-url", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             responses=COLLECTION_ERRORS | {200: {"model": ProductSummary, "description": "Collected before: refreshed"}},
             summary="Collect and analyse reviews from a product link (permitted sources only)")
def product_from_url(body: UrlRequest, response: Response, db: Session = Depends(get_db)):
    """Supported: Apple App Store app links. Amazon and Flipkart links are recognised but can’t be collected.
    Collecting the same product again adds any new reviews and runs a new analysis (status 200)."""
    product, created = collection.collect_from_url(db, body.url)
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return product_service.summary_out(product)


@router.get("/{product_id}", response_model=ProductSummary, responses=NOT_FOUND, summary="Get one product")
def get_product(product_id: int, db: Session = Depends(get_db)):
    return product_service.summary_out(product_service.get_product(db, product_id))


@router.patch("/{product_id}", response_model=ProductSummary, responses=NOT_FOUND,
              summary="Rename a product or change its brand/category")
def update_product(product_id: int, body: ProductUpdate, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise AppError("The product name can’t be empty.", 422)
    for field, value in changes.items():
        setattr(product, field, value)
    db.commit()
    return product_service.summary_out(product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND,
               summary="Delete a product with its reviews and analysis history")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    db.delete(product_service.get_product(db, product_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{product_id}/analysis", response_model=Analysis,
            responses=NOT_FOUND | {409: {"model": ErrorResponse, "description": "Not analysed yet"}},
            summary="Latest full analysis: stats, features, keywords, summary and every review")
def get_analysis(product_id: int, include_reviews: bool = Query(True, description="Include every review"),
                 db: Session = Depends(get_db)):
    return analysis_service.analysis_out(product_service.get_product(db, product_id), include_reviews)


@router.post("/{product_id}/analyze", response_model=Analysis,
             responses=NOT_FOUND | {422: {"model": ErrorResponse, "description": "No reviews to analyse"}},
             summary="Run the analysis again (for example after adding reviews)")
def reanalyze(product_id: int, include_reviews: bool = Query(True, description="Include every review"),
              db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    analysis_service.run_analysis(db, product)
    db.commit()
    return analysis_service.analysis_out(product, include_reviews)


@router.post("/{product_id}/refresh", response_model=ProductSummary, responses=NOT_FOUND | COLLECTION_ERRORS,
             summary="Collect the latest reviews again for a product added from a link")
def refresh_product(product_id: int, db: Session = Depends(get_db)):
    product = collection.refresh_product(db, product_service.get_product(db, product_id))
    return product_service.summary_out(product)


def _download_name(product, run, extension: str) -> str:
    # ASCII only: HTTP headers can't carry other characters (a Devanagari name crashed the download).
    slug = "-".join("".join(c if c.isascii() and c.isalnum() else " " for c in product.name.lower()).split())
    slug = slug[:40].strip("-")
    slug = slug or "product"
    return f"reviews-dekho-{slug}-run-{run.id}.{extension}"


@router.get("/{product_id}/report.csv", responses=NOT_FOUND | NOT_ANALYSED, response_class=Response,
            summary="Every review of an analysis run with its sentiment and features, as CSV")
def report_csv(product_id: int, analysis_id: int | None = Query(None, description="Default: the latest run"),
               include_reviewer: bool = Query(False, description="Add the reviewer-name column"),
               db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    run = review_query.pick_run(product, analysis_id)
    return Response(reports.reviews_csv(run, include_reviewer), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_download_name(product, run, "csv")}"'})


@router.get("/{product_id}/report.pdf", responses=NOT_FOUND | NOT_ANALYSED, response_class=Response,
            summary="PDF report of an analysis run: figures, charts, evidence-backed summary, method, limitations")
def report_pdf(product_id: int, analysis_id: int | None = Query(None, description="Default: the latest run"),
               db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    run = review_query.pick_run(product, analysis_id, require_reviews=False)
    return Response(build_report(product, run), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_download_name(product, run, "pdf")}"'})

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..errors import AppError
from ..models import Product
from ..schemas import Analysis, ErrorResponse, ProductCreate, ProductSummary, ProductUpdate, UrlRequest
from ..services import analysis as analysis_service
from ..services import products as product_service
from ..services import reports, sites

router = APIRouter(prefix="/products", tags=["Products"])
NOT_FOUND = {404: {"model": ErrorResponse, "description": "Product not found"}}


@router.get("", response_model=list[ProductSummary], summary="List all products, newest first")
def list_products(db: Session = Depends(get_db)):
    return [product_service.summary_out(p) for p in product_service.list_products(db)]


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             summary="Create an empty product (add reviews to it afterwards)")
def create_product(body: ProductCreate, db: Session = Depends(get_db)):
    product = Product(name=body.name, brand=body.brand, category=body.category, source="manual")
    db.add(product)
    db.commit()
    return product_service.summary_out(product)


@router.post("/from-url", response_model=ProductSummary, status_code=status.HTTP_201_CREATED,
             responses={422: {"model": ErrorResponse, "description": "Website not supported"}},
             summary="Analyse a product from its link (only permitted sources)")
def product_from_url(body: UrlRequest):
    sites.collect_from_url(str(body.url))  # raises a clear 422 explaining why the link can't be used


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
def get_analysis(product_id: int, db: Session = Depends(get_db)):
    return analysis_service.analysis_out(product_service.get_product(db, product_id))


@router.post("/{product_id}/analyze", response_model=Analysis,
             responses=NOT_FOUND | {422: {"model": ErrorResponse, "description": "No reviews to analyse"}},
             summary="Run the analysis again (for example after adding reviews)")
def reanalyze(product_id: int, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    analysis_service.run_analysis(db, product)
    db.commit()
    return analysis_service.analysis_out(product)


@router.get("/{product_id}/report.csv", responses=NOT_FOUND, response_class=Response,
            summary="Download every review with its sentiment and features as CSV")
def report_csv(product_id: int, db: Session = Depends(get_db)):
    product = product_service.get_product(db, product_id)
    if product.latest_analysis is None:
        raise AppError("This product hasn’t been analysed yet.", 409)
    filename = f"reviews-dekho-product-{product.id}.csv"
    return Response(reports.reviews_csv(product), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/{product_id}/report.pdf", responses=NOT_FOUND | {501: {"model": ErrorResponse}},
            summary="PDF report (not built yet)")
def report_pdf(product_id: int, db: Session = Depends(get_db)):
    product_service.get_product(db, product_id)
    raise AppError("PDF reports aren’t available yet. Download the CSV export instead.", 501)

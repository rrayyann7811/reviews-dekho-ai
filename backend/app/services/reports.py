"""Downloadable exports of an analysis."""
import csv
import io

from ..models import Product
from .analysis import current_reviews

CSV_COLUMNS = ["review_id", "rating", "date", "reviewer", "title", "text",
               "sentiment", "sentiment_score", "mixed_opinion", "features"]


def _safe(value) -> str:
    """Stop spreadsheet programs from treating a cell as a formula (CSV injection)."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def reviews_csv(product: Product) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for r in current_reviews(product):
        features = "; ".join(f"{a['aspect']} ({a['sentiment']})" for a in (r["aspects"] or []))
        writer.writerow([
            _safe(r["id"]), r["rating"] or "", r["date"] or "", _safe(r["reviewer"]), _safe(r["title"]),
            _safe(r["text"]), r["sentiment"] or "", "" if r["score"] is None else f"{r['score']:.3f}",
            "yes" if r["mixed"] else "no", _safe(features)])
    return "﻿" + buffer.getvalue()  # BOM so Excel opens it as UTF-8

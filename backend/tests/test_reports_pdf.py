"""PDF reports: correct run, numbers that match the stored snapshot, privacy, robustness."""
import re
import time
from datetime import datetime, timezone

import pytest
from reportlab.pdfbase import pdfmetrics
from sqlalchemy.orm import Session

from app.database import engine
from app.models import AnalysisResult, Product
from app.reports.pdf import CELL_PADDING, FEATURE_HEADERS, MISSING_GLYPH, build_report, feature_columns, report_text

from .conftest import csv_file, import_file

GENERATED = datetime(2026, 11, 14, tzinfo=timezone.utc)


def text_of(product_id: int, analysis_id: int | None = None) -> str:
    with Session(engine) as db:
        product = db.get(Product, product_id)
        run = db.get(AnalysisResult, analysis_id) if analysis_id else product.latest_analysis
        return report_text(product, run, GENERATED)


def pdf_pages(content: bytes) -> int:
    return len(re.findall(rb"/Type /Page\b", content))


def upload(client, text, columns, **extra):
    response = import_file(client, files=csv_file(text), columns=columns, **extra)
    assert response.status_code == 201, response.text
    return response.json()


# ---------- The endpoint ----------

def test_pdf_download(client, product):
    response = client.get(f"/api/products/{product['id']}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    run_id = client.get(f"/api/products/{product['id']}/analysis").json()["analysisId"]
    assert response.headers["content-disposition"] == f'attachment; filename="reviews-dekho-test-phone-run-{run_id}.pdf"'
    assert response.content.startswith(b"%PDF-") and response.content.rstrip().endswith(b"%%EOF")
    assert pdf_pages(response.content) >= 2


def test_pdf_errors(client, product):
    assert client.get("/api/products/999/report.pdf").status_code == 404
    empty = client.post("/api/products", json={"name": "Nothing yet"}).json()
    response = client.get(f"/api/products/{empty['id']}/report.pdf")
    assert response.status_code == 409 and "hasn’t been analysed" in response.json()["detail"]
    other = client.post("/api/products", json={"name": "Other"}).json()
    client.post(f"/api/products/{other['id']}/reviews", json={"reviews": [{"text": "Nice"}]})
    other_run = client.get(f"/api/products/{other['id']}/analysis").json()["analysisId"]
    assert client.get(f"/api/products/{product['id']}/report.pdf", params={"analysis_id": other_run}).status_code == 404


# ---------- Content matches the stored snapshot ----------

def test_every_figure_matches_the_stored_run(client):
    text = "id,review,stars,when,who\n" + "".join(
        f"{i},{t},{s},2026-10-{10 + i:02d},Person {i}\n" for i, (t, s) in enumerate([
            ("The battery is excellent and lasts all day", 5), ("Battery life is superb", 5),
            ('"Great battery, but the camera is terrible"', 3), ("The camera is awful and blurry", 1),
            ("Camera is poor in low light", 2), ("Delivery was late and the box was damaged", 1),
            ('"Superb display, very bright"', 5), ("Display is good", 4), ("The battery drains quickly", 2),
            ("bakwas phone hai yaar", 1)]))
    product = upload(client, text, {"text": "review", "rating": "stars", "date": "when", "id": "id", "reviewer": "who"})
    snap = client.get(f"/api/products/{product['id']}/analysis").json()
    report = text_of(product["id"])
    s = snap["stats"]
    assert f"\n{s['analysedReviews']}\nof {s['totalReviews']} in this run" in report
    assert f"\n{s['notAnalysed']['languageNotSupported']}\nnot in English" in report
    assert f"{s['averageRating']:.1f} / 5\nfrom {s['ratedReviews']} rated reviews" in report
    for key in ("positive", "neutral", "negative"):
        assert f"{s['sentimentCounts'][key]} of {s['analysedReviews']}" in report
    for aspect in snap["aspects"]:
        assert f"{aspect['aspect']}\n{aspect['mentions']}\n{aspect['positive']}\n{aspect['neutral']}\n{aspect['negative']}" in report
    for key in ("strengths", "complaints", "mixed"):
        for claim in snap["summary"][key]:
            assert claim["statement"] in report
            for excerpt in claim["evidence"]:
                assert f"“{excerpt['text']}”" in report and f"Review {excerpt['reviewId']}" in report
    assert snap["summary"]["overview"] in report
    assert f"#{snap['analysisId']} · analysed" in report and "latest run" in report


def test_reviewer_names_are_never_in_the_report(client, product):
    report = text_of(product["id"])
    for name in ("Asha", "Ravi", "Meera", "Karan", "Zoya", "Imran"):
        assert name not in report
    assert "Reviewer names are not included" in report


def test_earlier_runs_are_reported_from_their_own_snapshot(client, product):
    url = f"/api/products/{product['id']}"
    first = client.get(f"{url}/analysis").json()
    client.post(f"{url}/reviews", json={"reviews": [{"text": "A brand new review about the excellent battery",
                                                     "id": "NEW"}]})
    second = client.get(f"{url}/analysis").json()
    old_report, new_report = text_of(product["id"], first["analysisId"]), text_of(product["id"])
    assert f"of {first['stats']['totalReviews']} in this run" in old_report
    assert f"earlier run — a newer run (#{second['analysisId']}) exists" in old_report
    assert "Review NEW" not in old_report
    assert f"of {second['stats']['totalReviews']} in this run" in new_report and "latest run" in new_report
    via_api = client.get(f"{url}/report.pdf", params={"analysis_id": first["analysisId"]})
    assert via_api.status_code == 200 and f"run-{first['analysisId']}.pdf" in via_api.headers["content-disposition"]


def test_csv_follows_the_selected_run_too(client, product):
    url = f"/api/products/{product['id']}"
    first = client.get(f"{url}/analysis").json()["analysisId"]
    client.post(f"{url}/reviews", json={"reviews": [{"text": "Another one", "id": "NEW"}]})
    old_csv = client.get(f"{url}/report.csv", params={"analysis_id": first}).content.decode("utf-8-sig")
    assert "NEW" not in old_csv and "NEW" in client.get(f"{url}/report.csv").text


# ---------- Robustness ----------

# No ";" in it: a semicolon ends a clause, and excerpts are clauses.
HOSTILE = "<b>bold</b> & <script>alert(1)</script> <para>x</para> ]]> <font size=99>big</font> &copy &#60"


def test_markup_like_text_is_printed_literally(client):
    text = "id,review\n" + "".join(f'{i},"The battery is excellent {HOSTILE} #{i}"\n' for i in range(6))
    product = upload(client, text, {"text": "review", "id": "id"}, product_name="Phone <img src=x> &amp; Co")
    response = client.get(f"/api/products/{product['id']}/report.pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF-")
    report = text_of(product["id"])
    assert "Phone <img src=x> &amp; Co" in report
    assert HOSTILE in report  # shown as text, not interpreted as markup


def test_unicode_and_characters_the_font_cannot_draw(client):
    text = ("id,review\n" + "".join(f"{i},The battery is excellent 😍 worth every ₹ {i}\n" for i in range(5))
            + "9,Great camera 👍 and display\n")
    product = upload(client, text, {"text": "review", "id": "id"}, product_name="फ़ोन Kestrel")
    report = text_of(product["id"])
    download = client.get(f"/api/products/{product['id']}/report.pdf")
    assert download.status_code == 200
    assert download.headers["content-disposition"].startswith('attachment; filename="reviews-dekho-kestrel-run-')
    assert "😍" in report and "₹" in report                     # in DejaVu Sans
    assert f"{MISSING_GLYPH}{MISSING_GLYPH}{MISSING_GLYPH} Kestrel" in report  # Devanagari isn't
    assert "marks characters the report font can’t display" in report
    assert client.get(f"/api/products/{product['id']}/report.pdf").status_code == 200


def test_small_dataset(client):
    product = upload(client, "review,stars\nGreat battery,5\nAwful camera,1\n", {"text": "review", "rating": "stars"})
    report = text_of(product["id"])
    assert "Only 2 review(s) could be analysed" in report
    assert "Small sample (2 analysed reviews)" in report
    assert client.get(f"/api/products/{product['id']}/report.pdf").status_code == 200


def test_no_supported_language(client):
    product = upload(client, "review,stars\n\"bakwas app hai, paisa barbaad\",1\nyeh bahut kharab hai yaar,2\n",
                     {"text": "review", "rating": "stars"})
    report = text_of(product["id"])
    assert "No review could be analysed for tone" in report
    assert "Positive\n—\n0 of 0" in report  # no misleading 0%
    assert "No review could be analysed, so there is no summary." in report
    assert "There are too few analysed reviews for a summary." in report
    assert "No feature is clearly praised" not in report  # no empty claim groups
    assert "“" not in report  # nothing quoted
    assert client.get(f"/api/products/{product['id']}/report.pdf").status_code == 200


def test_no_star_ratings(client):
    product = upload(client, "review\n" + "".join(f"The battery is excellent {i}\n" for i in range(6)),
                     {"text": "review"})
    report = text_of(product["id"])
    assert "This data has no star ratings." in report and "from 0 rated reviews" in report


def test_old_run_without_review_results_or_evidence(client, product):
    with Session(engine) as db:
        run = db.get(Product, product["id"]).latest_analysis
        run.review_results = None
        run.summary = {k: v for k, v in run.summary.items() if k != "version"} | {
            "strengths": [{"aspect": "Battery", "mentions": 3, "count": 3, "percent": 100, "positive": 3,
                           "neutral": 0, "negative": 0, "example": {"reviewId": "A1", "text": "battery"}},
                          # positive and negative counts equal: the section, not the counts, decides the wording
                          {"aspect": "Display", "mentions": 4, "count": 2, "percent": 50, "positive": 2,
                           "neutral": 0, "negative": 2, "example": None}]}
        db.commit()
    response = client.get(f"/api/products/{product['id']}/report.pdf")
    assert response.status_code == 200
    report = text_of(product["id"])
    assert "stored without per-review results" in report
    assert "Battery: 3 of 3 mentions positive (100%)." in report and "summary version 1" in report
    assert "Display: 2 of 4 mentions positive (50%)." in report


def test_feature_table_headers_fit_their_columns():
    for header, width in zip(FEATURE_HEADERS, feature_columns()):
        assert pdfmetrics.stringWidth(header, "DejaVuSans-Bold", 8.5) <= width - 2 * CELL_PADDING


def test_same_run_same_pdf(client, product):
    with Session(engine) as db:
        p = db.get(Product, product["id"])
        assert build_report(p, p.latest_analysis, GENERATED) == build_report(p, p.latest_analysis, GENERATED)


@pytest.mark.slow
def test_twenty_thousand_reviews(client):
    phrases = ["The battery is excellent", "Battery drains fast", "The camera is terrible", "Great camera",
               "Delivery was late", "Superb display", "Price is too high", "Good value for the price",
               "Build quality is poor", "It works fine"]
    rows = "".join(f"{i},{phrases[i % 10]} — order {i},{1 + i % 5},2026-{1 + i % 12:02d}-{1 + i % 28:02d}\n"
                   for i in range(20_000))
    started = time.perf_counter()
    product = upload(client, "id,review,stars,when\n" + rows, {"text": "review", "id": "id", "rating": "stars",
                                                              "date": "when"})
    analysis_seconds = time.perf_counter() - started
    started = time.perf_counter()
    response = client.get(f"/api/products/{product['id']}/report.pdf")
    pdf_seconds = time.perf_counter() - started
    assert product["totalReviews"] == 20_000
    assert response.status_code == 200
    assert pdf_pages(response.content) <= 6           # aggregates and a few excerpts, not 20,000 reviews
    assert len(response.content) < 300_000
    report = text_of(product["id"])
    assert report.count("Review ") <= 3 * 9 + 5         # at most 3 excerpts per feature claim
    assert "20,000" in report
    assert pdf_seconds < 5, pdf_seconds
    print(f"\n20,000 reviews: import + analysis {analysis_seconds:.1f}s, PDF {pdf_seconds:.2f}s, "
          f"{len(response.content) // 1024} KB, {pdf_pages(response.content)} pages")

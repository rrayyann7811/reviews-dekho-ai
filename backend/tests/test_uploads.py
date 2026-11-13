"""CSV / Excel preview and import: valid files, invalid files and data cleaning."""
import json

import pytest

from app import config

from .conftest import DEMO_CSV, csv_file, import_file, xlsx_bytes

XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------- Preview ----------

def test_preview_csv_detects_columns(client):
    response = client.post("/api/uploads/preview", files=csv_file())
    assert response.status_code == 200
    body = response.json()
    assert body["fileName"] == "reviews.csv"
    assert body["rowCount"] == 6
    assert body["columns"][:3] == ["review_id", "product_name", "rating"]
    assert len(body["sampleRows"]) == 5
    assert body["detected"] == {"text": "review_text", "rating": "rating", "date": "review_date",
                                "title": "review_title", "reviewer": "reviewer_name",
                                "productName": "product_name", "id": "review_id"}
    assert body["productName"] == "Test Phone"
    assert body["warnings"] == []


def test_preview_does_not_save_anything(client):
    client.post("/api/uploads/preview", files=csv_file())
    assert client.get("/api/products").json() == []


def test_preview_xlsx(client):
    content = xlsx_bytes([{"Comment": "Really good blender, strong motor", "Stars": 5, "Date": "2026-01-02"},
                          {"Comment": "Broke after a week", "Stars": 1, "Date": "2026-01-03"}])
    body = client.post("/api/uploads/preview", files={"file": ("b.xlsx", content, XLSX_TYPE)}).json()
    assert body["rowCount"] == 2
    assert body["detected"]["text"] == "Comment" and body["detected"]["rating"] == "Stars"
    assert body["detected"]["date"] == "Date"
    assert body["sampleRows"][0]["Stars"] == "5"


def test_preview_handles_semicolons_bom_and_windows_encoding(client):
    semicolon = "﻿Kommentar;Bewertung\nSehr gut, café quality;5\nSchlecht;1\n"
    body = client.post("/api/uploads/preview", files=csv_file(semicolon)).json()
    assert body["columns"] == ["Kommentar", "Bewertung"]
    cp1252 = "review,stars\nGreat café machine – love it,5\n"
    body = client.post("/api/uploads/preview", files=csv_file(cp1252, encoding="cp1252")).json()
    assert body["sampleRows"][0]["review"] == "Great café machine – love it"


def test_preview_guesses_text_column_with_warning(client):
    text = "col_a,col_b\nThis product is wonderful and works perfectly,5\nNot what I expected at all sadly,2\n"
    body = client.post("/api/uploads/preview", files=csv_file(text)).json()
    assert body["detected"]["text"] == "col_a"
    assert "longest entries" in body["warnings"][0]


def test_preview_warns_when_no_text_column(client):
    body = client.post("/api/uploads/preview", files=csv_file("a,b\n1,2\n3,4\n")).json()
    assert body["detected"]["text"] is None
    assert body["warnings"] == ["No column looks like review text. Choose it below."]


def test_preview_warns_about_several_products(client):
    text = "product,review\nPhone A,Great phone overall\nPhone B,Bad phone overall\n"
    body = client.post("/api/uploads/preview", files=csv_file(text)).json()
    assert body["productName"] == "Phone A"
    assert "2 different product names" in body["warnings"][0]


def test_preview_drops_blank_rows_and_unnamed_empty_columns(client):
    text = "review,rating,\nGood one,5,\n,,\nBad one,1,\n"
    body = client.post("/api/uploads/preview", files=csv_file(text)).json()
    assert body["columns"] == ["review", "rating"]
    assert body["rowCount"] == 2


@pytest.mark.parametrize(("files", "status", "message"), [
    ({"file": ("notes.txt", b"hello", "text/plain")}, 415, "isn’t a CSV or Excel"),
    ({"file": ("old.xls", b"hello", "application/vnd.ms-excel")}, 415, "re-saved as .xlsx"),
    ({"file": ("empty.csv", b"", "text/csv")}, 400, "is empty"),
    ({"file": ("headers.csv", b"review,rating\n", "text/csv")}, 400, "no rows of data"),
    ({"file": ("blank.csv", b"\n\n\n", "text/csv")}, 400, "couldn’t be read"),
    ({"file": ("fake.xlsx", b"this is not a spreadsheet", XLSX_TYPE)}, 400, "couldn’t be opened"),
    ({"file": ("binary.csv", b"\x00\x01\x02\x00review", "text/csv")}, 400, "doesn’t look like a text CSV"),
])
def test_preview_rejects_invalid_files(client, files, status, message):
    response = client.post("/api/uploads/preview", files=files)
    assert response.status_code == status, response.text
    assert message in response.json()["detail"]


def test_preview_rejects_files_over_the_size_limit(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_UPLOAD_BYTES", 100)
    response = client.post("/api/uploads/preview", files=csv_file("review\n" + "x" * 200 + "\n"))
    assert response.status_code == 413
    assert "MB limit" in response.json()["detail"]


def test_preview_rejects_too_many_rows(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_ROWS", 3)
    response = client.post("/api/uploads/preview", files=csv_file("review\na\nb\nc\nd\n"))
    assert response.status_code == 413
    assert "limit is 3" in response.json()["detail"]


def test_preview_requires_a_file(client):
    response = client.post("/api/uploads/preview")
    assert response.status_code == 422
    assert "file" in response.json()["detail"]


# ---------- Import ----------

def test_import_creates_analysed_product(client):
    response = import_file(client, brand="Acme", category="Phones")
    assert response.status_code == 201
    product = response.json()
    assert product["name"] == "Test Phone" and product["brand"] == "Acme" and product["category"] == "Phones"
    assert product["source"] == "upload" and product["totalReviews"] == 6 and product["analyzedAt"]

    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["ingestion"] == {"rowsInFile": 6, "emptyRemoved": 0, "duplicatesRemoved": 0,
                                     "invalidRatings": 0, "invalidDates": 0, "truncated": 0,
                                     "imported": 6, "fileName": "reviews.csv"}
    assert [r["id"] for r in analysis["reviews"]] == ["A1", "A2", "A3", "A4", "A5", "A6"]


def test_import_xlsx(client):
    content = xlsx_bytes([{"Feedback": "Excellent quality and fast delivery", "Rating": 5},
                          {"Feedback": "Poor quality, very disappointed", "Rating": 1}])
    response = import_file(client, files={"file": ("x.xlsx", content, XLSX_TYPE)}, product_name="Mixer",
                           columns={"text": "Feedback", "rating": "Rating"})
    assert response.status_code == 201
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    assert [r["sentiment"] for r in analysis["reviews"]] == ["positive", "negative"]
    assert [r["id"] for r in analysis["reviews"]] == ["R-1", "R-2"]


def test_import_cleans_and_reports_problems(client):
    text = (
        "id,review,stars,when\n"
        "1,Great product,5,2026-03-01\n"
        "1,Same ID again so skipped,4,2026-03-02\n"
        "2,   ,3,2026-03-03\n"
        "3,Works fine,4/5,01/02/2026\n"
        "4,Rating is junk,ten,not a date\n"
        "5,Rating out of range,9,\n"
        "6,  Extra   spaces\tinside ,4.5 stars,\n"
    )
    response = import_file(client, files=csv_file(text), columns={
        "text": "review", "rating": "stars", "date": "when", "id": "id"})
    assert response.status_code == 201
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    report = analysis["ingestion"]
    assert report["rowsInFile"] == 7
    assert report["duplicatesRemoved"] == 1
    assert report["emptyRemoved"] == 1
    assert report["invalidRatings"] == 2
    assert report["invalidDates"] == 1
    assert report["imported"] == 5
    reviews = {r["id"]: r for r in analysis["reviews"]}
    assert reviews["3"]["rating"] == 4 and reviews["3"]["date"] == "2026-02-01"  # day-first
    assert reviews["4"]["rating"] is None and reviews["4"]["date"] is None
    assert reviews["5"]["rating"] is None
    assert reviews["6"]["text"] == "Extra spaces inside" and reviews["6"]["rating"] == 5


def test_import_skips_duplicate_text_when_there_is_no_id_column(client):
    text = "review\nLovely kettle!\nlovely kettle\nDifferent review\n"
    response = import_file(client, files=csv_file(text), columns={"text": "review"})
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    assert analysis["ingestion"]["duplicatesRemoved"] == 1
    assert [r["id"] for r in analysis["reviews"]] == ["R-1", "R-3"]


def test_generated_ids_do_not_clash_with_real_ids(client):
    text = "id,review\nR-2,First review text\n,Second review text\n"
    response = import_file(client, files=csv_file(text), columns={"text": "review", "id": "id"})
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    assert [r["id"] for r in analysis["reviews"]] == ["R-2", "R-2-2"]


def test_long_reviews_are_truncated(client, monkeypatch):
    monkeypatch.setattr(config, "MAX_REVIEW_CHARS", 20)
    response = import_file(client, files=csv_file("review\n" + "word " * 50 + "\n"), columns={"text": "review"})
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    assert analysis["ingestion"]["truncated"] == 1
    assert len(analysis["reviews"][0]["text"]) <= 20


@pytest.mark.parametrize(("columns", "message"), [
    ("not json", "column choices are invalid"),
    (json.dumps({"rating": "rating"}), "column choices are invalid"),
    (json.dumps({"text": None}), "column choices are invalid"),
    (json.dumps(["review_text"]), "column choices are invalid"),
    (json.dumps({"text": "missing_col"}), "These columns aren’t in the file: missing_col"),
    (json.dumps({"text": "review_text", "rating": "nope"}), "These columns aren’t in the file: nope"),
    (json.dumps({"text": ""}), "Choose the column that contains the review text"),
])
def test_import_rejects_bad_column_choices(client, columns, message):
    response = client.post("/api/uploads/import", files=csv_file(),
                           data={"product_name": "P", "columns": columns})
    assert response.status_code == 422
    assert message in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_import_rejects_blank_product_name(client):
    for name in ("", "   "):
        response = import_file(client, product_name=name)
        assert response.status_code == 422
    assert client.get("/api/products").json() == []


def test_import_rejects_file_with_no_review_text(client):
    response = import_file(client, files=csv_file("review,rating\n ,5\n,4\n"), columns={"text": "review"})
    assert response.status_code == 422
    assert "No usable reviews" in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_import_rejects_invalid_files(client):
    response = import_file(client, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 415
    assert client.get("/api/products").json() == []


def test_import_the_bundled_sample_file(client):
    preview = client.post("/api/uploads/preview",
                          files={"file": (DEMO_CSV.name, DEMO_CSV.read_bytes(), "text/csv")}).json()
    response = client.post("/api/uploads/import",
                           files={"file": (DEMO_CSV.name, DEMO_CSV.read_bytes(), "text/csv")},
                           data={"product_name": preview["productName"], "columns": json.dumps(preview["detected"])})
    assert response.status_code == 201
    analysis = client.get(f"/api/products/{response.json()['id']}/analysis").json()
    assert analysis["ingestion"]["rowsInFile"] == 65
    assert analysis["ingestion"]["duplicatesRemoved"] == 1
    assert analysis["ingestion"]["emptyRemoved"] == 1
    assert analysis["stats"]["totalReviews"] == 63


def test_malformed_csv_gives_a_helpful_message(client):
    response = client.post("/api/uploads/preview", files=csv_file("review\nfine\nhas, a comma\n"))
    assert response.status_code == 400
    assert "wrapped in double quotes" in response.json()["detail"]
    assert "\n" not in response.json()["detail"]

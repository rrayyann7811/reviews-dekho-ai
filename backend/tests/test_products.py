"""Product management, analysis endpoints, URL handling and exports."""


def test_create_list_get_update_delete_product(client):
    created = client.post("/api/products", json={"name": "  Kettle X ", "brand": "Acme", "category": ""})
    assert created.status_code == 201
    product = created.json()
    assert product["name"] == "Kettle X" and product["brand"] == "Acme" and product["category"] is None
    assert product["source"] == "manual" and product["totalReviews"] == 0 and product["analyzedAt"] is None

    assert [p["id"] for p in client.get("/api/products").json()] == [product["id"]]
    assert client.get(f"/api/products/{product['id']}").json()["name"] == "Kettle X"

    updated = client.patch(f"/api/products/{product['id']}", json={"category": "Kitchen"}).json()
    assert updated["category"] == "Kitchen" and updated["brand"] == "Acme"

    assert client.delete(f"/api/products/{product['id']}").status_code == 204
    assert client.get(f"/api/products/{product['id']}").status_code == 404
    assert client.get("/api/products").json() == []


def test_create_product_validation(client):
    assert client.post("/api/products", json={"name": "   "}).status_code == 422
    assert client.post("/api/products", json={}).status_code == 422
    assert client.post("/api/products", json={"name": "x" * 201}).status_code == 422


def test_update_rejects_empty_name(client, product):
    response = client.patch(f"/api/products/{product['id']}", json={"name": " "})
    assert response.status_code == 422


def test_missing_product_is_404_everywhere(client):
    for method, path in [("get", "/api/products/999"), ("patch", "/api/products/999"),
                         ("delete", "/api/products/999"), ("get", "/api/products/999/analysis"),
                         ("post", "/api/products/999/analyze"), ("get", "/api/products/999/report.csv")]:
        kwargs = {"json": {"name": "x"}} if method == "patch" else {}
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 404, path
        assert response.json()["detail"] == "Product 999 doesn’t exist. It may have been deleted."


def test_product_list_includes_analysis_numbers(client, product):
    [row] = client.get("/api/products").json()
    assert row["id"] == product["id"]
    assert row["source"] == "upload" and row["fileName"] == "reviews.csv"
    assert row["totalReviews"] == 6
    assert row["averageRating"] == round((5 + 1 + 4 + 2 + 3 + 5) / 6, 2)
    assert 0 <= row["positivePercent"] <= 100
    assert row["analyzedAt"].endswith("Z") or row["analyzedAt"].endswith("+00:00")


def test_analysis_of_unanalysed_product_is_409(client):
    product = client.post("/api/products", json={"name": "Empty"}).json()
    response = client.get(f"/api/products/{product['id']}/analysis")
    assert response.status_code == 409
    assert "hasn’t been analysed" in response.json()["detail"]
    reanalyze = client.post(f"/api/products/{product['id']}/analyze")
    assert reanalyze.status_code == 422
    assert "no reviews" in reanalyze.json()["detail"]


def test_reanalyze_creates_a_new_history_entry(client, product):
    first = client.get(f"/api/products/{product['id']}/analysis").json()
    second = client.post(f"/api/products/{product['id']}/analyze").json()
    assert second["analysisId"] != first["analysisId"]
    assert second["stats"] == first["stats"]
    assert second["ingestion"] == first["ingestion"]  # the upload's cleaning report is kept
    assert len(client.get("/api/history", params={"product_id": product["id"]}).json()) == 2


def test_delete_product_cascades_to_reviews_and_history(client, product):
    assert client.delete(f"/api/products/{product['id']}").status_code == 204
    assert client.get("/api/history").json() == []
    assert client.get(f"/api/products/{product['id']}/reviews").status_code == 404


def test_from_url_explains_why_links_cannot_be_collected(client):
    cases = {
        "https://www.amazon.in/dp/B0TEST": "Amazon doesn’t provide public access",
        "https://www.flipkart.com/item/p/itm123": "Flipkart doesn’t provide public access",
        "https://shop.example.com/product/1": "shop.example.com isn’t a supported website",
        "https://demo.reviewsdekho.test/product/kestrel-orbit-5g": "demo product is built into the app",
    }
    for url, message in cases.items():
        response = client.post("/api/products/from-url", json={"url": url})
        assert response.status_code == 422, url
        assert message in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_from_url_rejects_invalid_urls(client):
    for body in ({"url": "not a url"}, {"url": "ftp://x.com/a"}, {}):
        response = client.post("/api/products/from-url", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], str)


def test_csv_report(client, product):
    response = client.get(f"/api/products/{product['id']}/report.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].startswith("review_id,rating,date")
    assert len(lines) == 7
    assert lines[1].startswith("A1,5,2026-10-01,Asha,Love it,")


def test_csv_report_neutralises_spreadsheet_formulas(client):
    text = "review_text\n\"=HYPERLINK(\"\"http://x\"\")\"\n"
    created = client.post("/api/uploads/import", files={"file": ("f.csv", text.encode(), "text/csv")},
                          data={"product_name": "P", "columns": '{"text": "review_text"}'}).json()
    body = client.get(f"/api/products/{created['id']}/report.csv").content.decode("utf-8-sig")
    assert "'=HYPERLINK" in body


def test_pdf_report_is_not_available_yet(client, product):
    response = client.get(f"/api/products/{product['id']}/report.pdf")
    assert response.status_code == 501
    assert "CSV" in response.json()["detail"]

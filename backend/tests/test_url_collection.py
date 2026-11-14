"""Collecting reviews from product links.

Apple's servers are replaced by httpx.MockTransport, so these tests run offline and
can simulate failures. The feed structure matches what Apple actually returned when
the integration was verified live (see docs/PLAN.md); reviewer names are made up.
"""
import json
from urllib.parse import urlparse

import httpx
import pytest

from app import config
from app.collectors import apple_app_store
from app.collectors.base import UnsupportedLink
from app.collectors.registry import find_adapter, validate_url
from app.services import collection

APP_ID = "1234567890"
APP_URL = f"https://apps.apple.com/in/app/sample-notes/id{APP_ID}"
LOOKUP = {"resultCount": 1, "results": [{
    "trackId": int(APP_ID), "trackName": "Sample Notes", "sellerName": "Sample Labs Pvt Ltd",
    "primaryGenreName": "Productivity", "averageUserRating": 4.5, "userRatingCount": 1200,
    "trackViewUrl": f"https://apps.apple.com/in/app/sample-notes/id{APP_ID}?uo=4"}]}


def entry(review_id, text, rating="5", title="Title", author="Test User", updated="2026-11-12T01:10:39-07:00"):
    return {"author": {"uri": {"label": "https://itunes.apple.com/in/reviews/id1"}, "name": {"label": author},
                       "label": ""},
            "updated": {"label": updated}, "im:rating": {"label": rating}, "im:version": {"label": "1.0"},
            "id": {"label": review_id}, "title": {"label": title},
            "content": {"label": text, "attributes": {"type": "text"}},
            "im:voteSum": {"label": "0"}, "im:voteCount": {"label": "0"}}


def feed(*entries):
    body = {"author": {"name": {"label": "iTunes Store"}}}
    if entries:
        body["entry"] = list(entries)
    return {"feed": body}


PAGE_1 = feed(entry("1001", "Love this app, syncing is fast and reliable.", "5", author="Asha T."),
              entry("1002", "Terrible update, the app crashes every time I open it.", "1", author="Ravi K."),
              entry("1003", "It works.", "3"))


class FakeApple:
    """Plays the role of Apple's servers. `pages` maps page number -> JSON body, or an exception/status."""

    def __init__(self, pages=None, lookup=LOOKUP):
        self.pages = pages if pages is not None else {1: PAGE_1}
        self.lookup = lookup
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path == "/lookup":
            return self._respond(self.lookup)
        page = int(request.url.path.split("page=")[1].split("/")[0])
        return self._respond(self.pages.get(page, 400))

    @staticmethod
    def _respond(value):
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return httpx.Response(value, text="error")
        if isinstance(value, str):
            return httpx.Response(200, text=value)
        return httpx.Response(200, json=value)


@pytest.fixture
def apple(monkeypatch):
    """Route every collector request to a FakeApple instead of the internet."""
    fake = FakeApple()
    monkeypatch.setattr(config, "APPLE_PAGE_DELAY_SECONDS", 0)
    # `fake.handler` is looked up on every request, so a test can swap it.
    monkeypatch.setattr(collection, "make_client",
                        lambda: httpx.Client(transport=httpx.MockTransport(lambda r: fake.handler(r))))
    return fake


def collect(client, url=APP_URL):
    return client.post("/api/products/from-url", json={"url": url})


# ---------- URL validation and website detection ----------

@pytest.mark.parametrize("raw", [
    "https://apps.apple.com/in/app/sample-notes/id1234567890",
    "apps.apple.com/in/app/sample-notes/id1234567890",
    "http://www.amazon.in/dp/B0ABCDEFGH",
    "  https://example.com/x  ",
])
def test_valid_urls(raw):
    assert validate_url(raw).hostname


@pytest.mark.parametrize("raw", ["", "   ", "not a url", "ftp://example.com/a", "https://localhost/x",
                                 "https://user:pass@apps.apple.com/in/app/id1234567", "https://exa mple.com",
                                 "https://" + "a" * 2000 + ".com"])
def test_invalid_urls(raw):
    with pytest.raises(UnsupportedLink):
        validate_url(raw)


@pytest.mark.parametrize(("raw", "site"), [
    ("https://apps.apple.com/in/app/x/id1234567", "apple_app_store"),
    ("https://itunes.apple.com/us/app/x/id1234567", "apple_app_store"),
    ("https://www.amazon.in/dp/B0ABCDEFGH", "amazon"),
    ("https://amzn.in/d/abc", "amazon"),
    ("https://www.flipkart.com/x/p/itm123", "flipkart"),
    ("https://demo.reviewsdekho.test/product/kestrel-orbit-5g", "demo"),
    ("https://shop.example.com/p/1", None),
    ("https://notamazon.in/dp/B0ABCDEFGH", None),
])
def test_website_detection(raw, site):
    adapter = find_adapter(validate_url(raw))
    assert (adapter.id if adapter else None) == site


@pytest.mark.parametrize(("path", "country", "app_id"), [
    ("/in/app/whatsapp-messenger/id310633997", "in", "310633997"),
    ("/US/app/some-app/id284882215/", "us", "284882215"),
    ("/app/id284882215", config.APPLE_DEFAULT_COUNTRY, "284882215"),
    ("/gb/app/id284882215", "gb", "284882215"),
])
def test_apple_links_are_parsed(path, country, app_id):
    ref = apple_app_store.AppleAppStoreAdapter().parse(urlparse(f"https://apps.apple.com{path}?platform=iphone"))
    assert (ref.region, ref.product_id) == (country, app_id)
    assert ref.url == f"https://apps.apple.com/{country}/app/id{app_id}"


def test_sites_endpoint_lists_what_works(client):
    sites = {s["id"]: s for s in client.get("/api/sites").json()}
    assert sites["apple_app_store"]["status"] == "supported"
    assert sites["amazon"]["status"] == "unavailable" and sites["flipkart"]["status"] == "unavailable"
    assert sites["apple_app_store"]["example"].startswith("https://apps.apple.com/")


def test_restricted_sites_never_make_network_requests(client, apple):
    response = collect(client, "https://www.amazon.in/Some-Phone/dp/B0ABCDEFGH/ref=sr_1_1")
    assert response.status_code == 422
    assert response.json()["detail"].startswith("This is Amazon product B0ABCDEFGH.")
    assert "upload them instead" in response.json()["detail"]
    flipkart = collect(client, "https://www.flipkart.com/phone/p/itmabc123?pid=X")
    assert flipkart.json()["detail"].startswith("This is Flipkart item itmabc123.")
    unsupported = collect(client, "https://shop.example.com/p/1")
    assert "Reviews can be collected from: Apple App Store" in unsupported.json()["detail"]
    assert apple.requests == []
    assert client.get("/api/products").json() == []


# ---------- Successful collection ----------

def test_collects_stores_and_analyses_reviews(client, apple):
    response = collect(client)
    assert response.status_code == 201
    product = response.json()
    assert product["name"] == "Sample Notes" and product["brand"] == "Sample Labs Pvt Ltd"
    assert product["category"] == "Productivity" and product["source"] == "url"
    assert product["sourceSite"] == "apple_app_store" and product["sourceSiteName"] == "Apple App Store"
    assert product["sourceRegion"] == "in" and product["collectedAt"]
    assert product["sourceUrl"] == APP_URL  # tracking parameters removed
    assert product["totalReviews"] == 3 and product["averageRating"] == 3.0

    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["product"]["sourceSiteName"] == "Apple App Store"
    first = analysis["reviews"][0]
    assert first == first | {"id": "1001", "rating": 5, "date": "2026-11-12", "title": "Title",
                             "reviewer": "Asha T.", "sentiment": "positive"}
    assert analysis["reviews"][1]["sentiment"] == "negative"
    report = analysis["ingestion"]
    assert report | {"collectedAt": None} == report | {
        "source": "Apple App Store", "region": "IN", "received": 3, "imported": 3, "newReviews": 3,
        "alreadyStored": 0, "pagesRead": 1, "storeRating": 4.5, "storeRatingCount": 1200, "collectedAt": None}
    assert "500 most recent" in report["sourceLimit"]
    # Requests went only to Apple's fixed API addresses, never to the link itself.
    assert all(u.startswith("https://itunes.apple.com/") for u in apple.requests)


def test_reads_every_page_until_apple_says_stop(client, apple):
    apple.pages = {p: feed(*[entry(f"{p}-{i}", f"Review {p}-{i} is good") for i in range(3)]) for p in (1, 2, 3)}
    product = collect(client).json()
    assert product["totalReviews"] == 9
    assert sum("/rss/" in u for u in apple.requests) == 4  # pages 1-3, then page 4 answered 400


def test_stops_at_the_page_limit(client, apple, monkeypatch):
    monkeypatch.setattr(config, "APPLE_MAX_PAGES", 2)
    apple.pages = {p: feed(entry(f"r{p}", f"Nice app number {p}")) for p in range(1, 6)}
    assert collect(client).json()["totalReviews"] == 2


def test_an_empty_page_in_the_middle_is_skipped(client, apple):
    # Seen live: Apple returned page 2 empty while pages 3-10 had reviews.
    apple.pages = {1: feed(entry("a", "Great app")), 2: feed(), 3: feed(entry("c", "Bad app"))}
    product = collect(client).json()
    assert product["totalReviews"] == 2
    page_2_requests = [u for u in apple.requests if "page=2/" in u]
    assert len(page_2_requests) == 2  # asked twice before moving on


def test_two_empty_pages_in_a_row_end_the_collection(client, apple):
    apple.pages = {1: feed(entry("a", "Great app")), 2: feed(), 3: feed(), 4: feed(entry("d", "Never read"))}
    assert collect(client).json()["totalReviews"] == 1


def test_a_single_review_page_object_is_handled(client, apple):
    apple.pages = {1: {"feed": {"entry": entry("only", "Only one review, and it is great")}}}
    assert collect(client).json()["totalReviews"] == 1


def test_app_description_entries_are_ignored(client, apple):
    app_entry = {"im:name": {"label": "Sample Notes"}, "id": {"label": "app"}, "title": {"label": "Sample"}}
    apple.pages = {1: feed(app_entry, entry("r1", "Useful and simple"))}
    analysis_id = collect(client).json()["id"]
    assert [r["id"] for r in client.get(f"/api/products/{analysis_id}/analysis").json()["reviews"]] == ["r1"]


# ---------- Messy data ----------

def test_duplicate_empty_and_malformed_reviews_are_cleaned(client, apple):
    apple.pages = {1: feed(
        entry("1", "Great app, love it"),
        entry("1", "Same ID repeated"),
        entry("2", "   "),
        entry("3", "No rating given", rating=""),
        entry("4", "Rating is nonsense", rating="lots"),
        entry("5", "Bad date", updated="sometime"),
        {"im:rating": {"label": "4"}, "id": {"label": "6"}},  # no text at all
    )}
    product = collect(client).json()
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    report = analysis["ingestion"]
    assert report["received"] == 7 and report["imported"] == 4
    assert report["duplicatesRemoved"] == 1 and report["emptyRemoved"] == 2
    assert report["invalidRatings"] == 1 and report["invalidDates"] == 1
    by_id = {r["id"]: r for r in analysis["reviews"]}
    assert by_id["3"]["rating"] is None and by_id["4"]["rating"] is None and by_id["5"]["date"] is None


def test_collecting_again_adds_only_new_reviews(client, apple):
    first = collect(client).json()
    apple.pages = {1: feed(entry("1004", "New review: much better now, thank you!"), *PAGE_1["feed"]["entry"])}
    again = collect(client, f"https://apps.apple.com/in/app/sample-notes/id{APP_ID}?see-all=reviews")
    assert again.status_code == 200 and again.json()["id"] == first["id"]
    analysis = client.get(f"/api/products/{first['id']}/analysis").json()
    assert analysis["ingestion"]["newReviews"] == 1 and analysis["ingestion"]["alreadyStored"] == 3
    assert sorted(r["id"] for r in analysis["reviews"]) == ["1001", "1002", "1003", "1004"]
    assert len(client.get("/api/products").json()) == 1
    assert len(client.get("/api/history").json()) == 2


def test_other_country_is_a_separate_product(client, apple):
    collect(client)
    collect(client, f"https://apps.apple.com/us/app/sample-notes/id{APP_ID}")
    regions = sorted(p["sourceRegion"] for p in client.get("/api/products").json())
    assert regions == ["in", "us"]


def test_refresh_endpoint(client, apple):
    product = collect(client).json()
    apple.pages = {1: feed(entry("2001", "Fresh review, works great"))}
    refreshed = client.post(f"/api/products/{product['id']}/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["totalReviews"] == 4


def test_refresh_is_only_for_collected_products(client, product):
    response = client.post(f"/api/products/{product['id']}/refresh")
    assert response.status_code == 422
    assert "Only products collected from a supported link" in response.json()["detail"]
    assert client.post("/api/products/999/refresh").status_code == 404


# ---------- Failures: nothing is saved, and the message says what happened ----------

@pytest.mark.parametrize(("lookup", "status", "message"), [
    ({"resultCount": 0, "results": []}, 404, "No app with ID 1234567890 was found in the App Store for country “IN”"),
    (httpx.ConnectError("no route"), 502, "Couldn’t connect to Apple App Store"),
    (httpx.ReadTimeout("slow"), 504, "Apple App Store took too long to respond"),
    (429, 503, "limiting how often"),
    (500, 502, "returned an error (HTTP 500)"),
    ("<html>not json</html>", 502, "couldn’t be read"),
])
def test_lookup_failures(client, apple, lookup, status, message):
    apple.lookup = lookup
    response = collect(client)
    assert response.status_code == status
    assert message in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_network_failure_on_the_first_review_page(client, apple):
    apple.pages = {1: httpx.ConnectError("down")}
    response = collect(client)
    assert response.status_code == 502
    assert client.get("/api/products").json() == []


def test_network_failure_after_some_pages_keeps_what_was_collected(client, apple):
    apple.pages = {1: PAGE_1, 2: httpx.ReadTimeout("slow")}
    product = collect(client).json()
    assert product["totalReviews"] == 3
    report = client.get(f"/api/products/{product['id']}/analysis").json()["ingestion"]
    assert "took too long" in report["stoppedEarly"]


def test_app_without_reviews(client, apple):
    apple.pages = {1: feed()}
    response = collect(client)
    assert response.status_code == 422
    assert "has no written reviews in the IN App Store yet" in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_reviews_without_any_text(client, apple):
    apple.pages = {1: feed(entry("1", ""), entry("2", "   "))}
    response = collect(client)
    assert response.status_code == 422
    assert "none had any written text" in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_unknown_app_page_on_apple(client, apple):
    response = collect(client, "https://apps.apple.com/in/developer/sample/id123456")
    assert response.status_code == 422
    assert "isn’t an app page" in response.json()["detail"]
    assert apple.requests == []


def test_collected_data_survives_restart_and_matches_the_pipeline(client, apple):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.nlp.pipeline import analyze_reviews

    product = collect(client).json()
    before = client.get(f"/api/products/{product['id']}/analysis").json()
    with TestClient(create_app()) as restarted:
        assert restarted.get(f"/api/products/{product['id']}/analysis").json() == before
    direct = analyze_reviews([{k: r[k] for k in ("id", "text", "rating", "date", "title", "reviewer")}
                              for r in before["reviews"]])
    assert direct["stats"] == before["stats"]


def test_collection_report_is_json_serialisable(client, apple):
    product = collect(client).json()
    detail = client.get(f"/api/history?product_id={product['id']}").json()[0]
    assert json.dumps(client.get(f"/api/history/{detail['id']}").json())


# ---------- Found in the pre-commit review ----------

@pytest.mark.parametrize(("lookup", "pages", "status"), [
    ([], None, 404),                                                    # lookup is not an object
    ({"results": "x"}, None, 404),                                      # results is not a list
    ({"results": [42, None]}, None, 404),                               # results are not objects
    (LOOKUP, {1: []}, 502),                                             # review page is not a feed
    (LOOKUP, {1: {"feed": "oops"}}, 502),
])
def test_malformed_responses_give_clear_errors_not_crashes(client, apple, lookup, pages, status):
    apple.lookup = lookup
    if pages is not None:
        apple.pages = pages
    response = collect(client)
    assert response.status_code == status
    assert "Something went wrong" not in response.json()["detail"]
    assert client.get("/api/products").json() == []


def test_malformed_entries_and_fields_are_skipped_or_treated_as_missing(client, apple):
    apple.lookup = {"results": [LOOKUP["results"][0] | {"trackName": 123, "averageUserRating": "high",
                                                         "userRatingCount": True}]}
    apple.pages = {1: {"feed": {"entry": [
        "not an entry", 7, None,
        entry("1", "Good app") | {"author": {"name": "Plain string"}},
        entry("2", "Nice app") | {"content": ["a", "b"]},                      # no usable text
        entry("3", "Fine app") | {"content": [{"label": "<b>Fine</b>", "attributes": {"type": "html"}},
                                               {"label": "Fine app, works", "attributes": {"type": "text"}}]},
    ]}}}
    product = collect(client).json()
    assert product["name"] == f"App {APP_ID}"
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    by_id = {r["id"]: r for r in analysis["reviews"]}
    assert set(by_id) == {"1", "3"} and by_id["1"]["reviewer"] == "Plain string"
    assert by_id["3"]["text"] == "Fine app, works"
    assert analysis["ingestion"]["storeRating"] is None and analysis["ingestion"]["storeRatingCount"] is None


@pytest.mark.parametrize("track_url", ["javascript:alert(1)", "https://evil.example/app", "http://apps.apple.com/x",
                                       "https://apps.apple.com.evil.example/x", None])
def test_only_genuine_apple_links_are_stored(client, apple, track_url):
    apple.lookup = {"results": [LOOKUP["results"][0] | {"trackViewUrl": track_url}]}
    assert collect(client).json()["sourceUrl"] == f"https://apps.apple.com/in/app/id{APP_ID}"


def test_the_database_is_not_locked_while_waiting_for_the_website(client, apple):
    """Another request must be able to write while a collection waits on the network."""
    import sqlite3

    from app import config as app_config

    path = app_config.DATABASE_URL.removeprefix("sqlite:///")
    original = apple.handler
    writes = []

    def handler_that_writes_meanwhile(request):
        if not writes:
            other = sqlite3.connect(path, timeout=0.5)
            other.execute("INSERT INTO products (name, source, created_at) VALUES ('Other', 'manual', '2026-01-01')")
            other.commit()
            other.close()
            writes.append(True)
        return original(request)

    apple.handler = handler_that_writes_meanwhile
    product = client.post("/api/products", json={"name": "Existing"}).json()  # a read happens first in refresh
    assert collect(client).status_code == 201
    assert writes == [True]
    assert {p["name"] for p in client.get("/api/products").json()} == {"Existing", "Other", "Sample Notes"}
    assert product["id"]

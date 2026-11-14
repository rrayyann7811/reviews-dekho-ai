"""Evidence-backed summary (summary version 2): every claim traceable to the stored snapshot."""
import pytest

from app.nlp.pipeline import analyze_reviews
from app.nlp.summary import MAX_EXCERPTS, SUMMARY_VERSION, select_evidence

from .conftest import csv_file, import_file

PHONE_REVIEWS = [
    {"id": f"P{i}", "text": text, "rating": rating, "title": title}
    for i, (text, rating, title) in enumerate([
        ("Battery life is excellent, lasts two days", 5, "Great"),
        ("The battery is superb and charging is quick", 5, None),
        ("Amazing battery backup, really impressed", 4, None),
        ("Battery is good", 4, None),
        ("Battery drains fast and the camera is terrible", 1, "Bad"),
        ("The camera is awful in low light", 2, None),
        ("Camera quality is poor and blurry", 1, None),
        ("The camera is great in daylight", 5, None),
        ("Delivery was quick", 5, None),
        ("bakwas phone hai, battery bekar", 1, None),  # Hinglish: never quoted
        ("Superb battery, love it", 5, None),
        ("superb battery love it!!", 5, None),         # near-duplicate of the one above
    ])
]


def summary_of(reviews=PHONE_REVIEWS, **kwargs):
    result = analyze_reviews(reviews, engine_preference="vader", **kwargs)
    return result, result["summary"]


def all_claims(summary):
    return [c for key in ("strengths", "complaints", "mixed") for c in summary[key]]


def test_claims_carry_statement_counts_and_evidence():
    result, summary = summary_of()
    assert summary["version"] == SUMMARY_VERSION == 2
    claims = all_claims(summary)
    assert claims
    rows = {a["aspect"]: a for a in result["aspects"]}
    for claim in claims:
        row = rows[claim["aspect"]]
        assert (claim["mentions"], claim["positive"], claim["neutral"], claim["negative"]) == (
            row["mentions"], row["positive"], row["neutral"], row["negative"])
        assert claim["analysedReviews"] == result["stats"]["analysedReviews"]
        assert str(claim["mentions"]) in claim["statement"] and str(claim["count"]) in claim["statement"]
        assert 1 <= len(claim["evidence"]) <= MAX_EXCERPTS
        assert claim["example"] == claim["evidence"][0]


def test_every_excerpt_is_exact_text_from_an_analysed_review():
    result, summary = summary_of()
    by_id = {r["id"]: r for r in result["reviews"]}
    for claim in all_claims(summary):
        for excerpt in claim["evidence"]:
            review = by_id[excerpt["reviewId"]]
            assert excerpt["text"] in (review[excerpt["field"]] or "")
            assert review["status"] == "analysed" and review["sentiment"] is not None
            assert excerpt["rating"] == review["rating"]
            assert "reviewer" not in excerpt


def test_unsupported_language_reviews_are_never_quoted():
    _, summary = summary_of()
    quoted = {e["reviewId"] for c in all_claims(summary) for e in c["evidence"]}
    assert "P9" not in quoted


def test_strengths_quote_positive_and_complaints_quote_negative():
    _, summary = summary_of()
    for claim in summary["strengths"]:
        assert all(e["sentiment"] == "positive" for e in claim["evidence"])
    for claim in summary["complaints"]:
        assert all(e["sentiment"] == "negative" for e in claim["evidence"])


def test_near_duplicates_are_removed():
    _, summary = summary_of()
    battery = next(c for c in summary["strengths"] if c["aspect"] == "Battery")
    texts = [e["text"].lower() for e in battery["evidence"]]
    assert not ("superb battery, love it" in texts and "superb battery love it!!" in texts)
    assert len({e["reviewId"] for e in battery["evidence"]}) == len(battery["evidence"])


def test_selection_is_deterministic():
    first = summary_of()[1]
    shuffled = summary_of(list(reversed(PHONE_REVIEWS)))[1]
    assert summary_of()[1] == first
    assert [e["reviewId"] for c in all_claims(shuffled) for e in c["evidence"]] == \
        [e["reviewId"] for c in all_claims(first) for e in c["evidence"]]


def test_a_review_already_quoted_is_used_again_only_if_nothing_else_exists():
    reviews = [{"id": "a", "text": "Great battery", "sentiment": "positive", "status": "analysed",
                "aspects": [{"aspect": "Battery", "sentiment": "positive", "score": 0.9, "snippet": "Great battery"}]},
               {"id": "b", "text": "Good battery life", "sentiment": "positive", "status": "analysed",
                "aspects": [{"aspect": "Battery", "sentiment": "positive", "score": 0.5, "snippet": "Good battery life"}]}]
    assert [e["reviewId"] for e in select_evidence("Battery", ["positive"], reviews, quoted_elsewhere={"a"})] == ["b", "a"]
    assert [e["reviewId"] for e in select_evidence("Battery", ["positive"], reviews[:1], quoted_elsewhere={"a"})] == ["a"]


def test_excerpts_that_are_not_verbatim_are_dropped():
    # The analysed text had its "!!!!!" shortened; that snippet no longer matches the stored text exactly.
    reviews = [{"id": "x", "text": "Battery is great!!!!!", "sentiment": "positive", "status": "analysed",
                "aspects": [{"aspect": "Battery", "sentiment": "positive", "score": 0.8, "snippet": "Battery is great!!!"}]}]
    assert select_evidence("Battery", ["positive"], reviews) == [
        {"reviewId": "x", "text": "Battery is great!!!", "field": "text", "sentiment": "positive",
         "rating": None, "date": None}]  # "great!!!" is a substring of "great!!!!!", so it is still verbatim
    reviews[0]["aspects"][0]["snippet"] = "Battery is GREAT"
    assert select_evidence("Battery", ["positive"], reviews) == []


def test_title_excerpts_are_marked():
    reviews = [{"id": f"t{i}", "text": "Fine", "title": "The battery is excellent", "rating": 5} for i in range(5)]
    _, summary = summary_of(reviews)
    claim = summary["strengths"][0]
    assert claim["evidence"][0]["field"] == "title" and claim["evidence"][0]["text"] == "The battery is excellent"


def test_wording_never_suggests_the_sample_is_everyone():
    _, summary = summary_of()
    assert summary["overview"].startswith("In this sample of 11 analysed reviews")
    assert any("not every customer" in note for note in summary["notes"])
    assert any("feature counts don’t add up" in note for note in summary["notes"])
    for claim in all_claims(summary):
        assert "analysed reviews that mention it" in claim["statement"]


@pytest.mark.parametrize(("reviews", "note"), [
    ([{"id": "1", "text": "Great battery"}, {"id": "2", "text": "Awful camera"}], "Only 2 review(s) could be analysed"),
    ([{"id": "1", "text": "bakwas app hai yaar"}, {"id": "2", "text": "bahut kharab hai"}],
     "No review could be analysed, so there is no summary."),
    ([], "No review could be analysed, so there is no summary."),
])
def test_too_few_or_no_analysed_reviews(reviews, note):
    _, summary = summary_of(reviews)
    assert summary["notes"][0].startswith(note)
    assert summary["overview"] is None and summary["overviewClaim"] is None
    assert not all_claims(summary)


def test_stored_runs_keep_their_summary_version(client, product):
    analysis = client.get(f"/api/products/{product['id']}/analysis").json()
    assert analysis["summary"]["version"] == 2
    assert analysis["summary"]["overviewClaim"]["analysedReviews"] == analysis["stats"]["analysedReviews"]


def test_upload_flow_produces_evidence(client):
    text = "id,review,stars\n" + "".join(f"{i},The battery is excellent number {i},5\n" for i in range(6))
    product = import_file(client, files=csv_file(text), columns={"text": "review", "id": "id", "rating": "stars"}).json()
    summary = client.get(f"/api/products/{product['id']}/analysis").json()["summary"]
    assert summary["strengths"][0]["evidence"]


def test_a_tie_is_not_reported_as_a_majority():
    # Seen in the live AI test: 6 positive and 6 negative reviews were summarised as "mostly positive".
    reviews = [{"id": f"p{i}", "text": "The battery is excellent and I love it"} for i in range(6)]
    reviews += [{"id": f"n{i}", "text": "The camera is terrible and I hate it"} for i in range(6)]
    _, summary = summary_of(reviews)
    assert "50.0% read as positive, 50.0% as negative" in summary["overview"]
    assert "so no single tone is in the majority" in summary["overview"]
    assert "mostly" not in summary["overview"]


def test_the_largest_share_without_a_majority_is_not_called_mostly():
    # Seen in the live AI test (round 4): 12 positive, 10 negative, 2 neutral (50.0%) was summarised as "mostly positive".
    from app.nlp.summary import is_majority
    assert is_majority({"positive": 13, "neutral": 2, "negative": 10}, "positive")
    assert not is_majority({"positive": 12, "neutral": 2, "negative": 10}, "positive")      # exactly half
    assert not is_majority({"positive": 9, "neutral": 6, "negative": 5}, "positive")        # 45%: largest, not a majority
    reviews = [{"id": f"p{i}", "text": "The battery is excellent and I love it"} for i in range(6)]
    reviews += [{"id": f"n{i}", "text": "The camera is terrible and I hate it"} for i in range(5)]
    reviews += [{"id": "z0", "text": "It is a phone with a battery"}]
    result, summary = summary_of(reviews)
    counts = result["stats"]["sentimentCounts"]
    assert counts["positive"] * 2 <= sum(counts.values()) and counts["positive"] > counts["negative"]
    assert "so positive is the most common tone, but not a majority" in summary["overview"]
    assert "mostly" not in summary["overview"]

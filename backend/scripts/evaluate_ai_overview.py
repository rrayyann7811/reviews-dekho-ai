"""Live evaluation of the optional AI overview with a local Ollama model — synthetic cases only.

Run from backend/ with Ollama running and the model pulled (nothing is started or downloaded by this script):
    .venv/bin/python scripts/evaluate_ai_overview.py                       # writes storage/ai_eval/<timestamp>.json
    .venv/bin/python scripts/evaluate_ai_overview.py --out ../docs/evaluation/ai_overview/run.json

Method
  * Each case (scripts/ai_eval_cases.py, plus the synthetic bundled sample) is imported into a fresh temporary
    database through the real API, analysed with the default sentiment engine, and sent once to
    POST /api/products/{id}/ai-summary — the same code path as the app: evidence package -> local model
    (temperature 0, fixed seed, JSON schema) -> automatic checker -> at most one retry -> accepted or rejected.
  * Recorded: model name and digest, Ollama version, generation settings, prompt version, timestamps, per-case
    status, attempts, timings, every raw model answer, checker findings and the accepted sentences.
  * Manual review is NOT automated and NOT invented: the output contains a review sheet with each accepted sentence
    next to the exact claims and excerpts it cites, and an empty "label" for a person to fill in
    (fully / partially / unsupported). The automatic checker is not a guarantee of factual accuracy.
  * Only synthetic reviews are used, so the output can be shared. Real App Store cases are deliberately excluded.
If Ollama or the model isn't available, the script says why and exits with code 3 without writing anything.
"""
import argparse
import datetime as dt
import json
import os
import platform
import statistics
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SAMPLE = BACKEND / "data" / "sample" / "demo_kestrel_orbit_5g.csv"
HARNESS_VERSION = 1
METHOD = ("Synthetic cases imported into a fresh temporary database through the real API; one POST /ai-summary per "
          "case (the app's own path: evidence package, local model at temperature 0 with a fixed seed and a JSON "
          "schema, automatic checker, at most one retry). Accepted sentences need a separate manual review against "
          "their cited evidence; this script never assigns those labels.")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def stats(values: list[float]) -> dict | None:
    if not values:
        return None
    return {"n": len(values), "mean": round(statistics.mean(values), 1), "median": round(statistics.median(values), 1),
            "min": round(min(values), 1), "max": round(max(values), 1)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the optional AI overview on synthetic cases.")
    parser.add_argument("--out", help="Output JSON (default: storage/ai_eval/ai-overview-<UTC time>.json)")
    args = parser.parse_args(argv)

    workdir = Path(tempfile.mkdtemp(prefix="ai-eval-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{workdir / 'ai_eval.db'}"   # never the real database
    os.environ["AI_SUMMARIES"] = "on"
    sys.path.insert(0, str(BACKEND))
    sys.path.insert(0, str(BACKEND / "scripts"))
    import httpx
    from fastapi.testclient import TestClient

    from ai_eval_cases import CASES
    from app import config
    from app.main import app
    from app.services import ai_summary
    from app.version import VERSION

    status = ai_summary.availability()
    if not status["available"]:
        print(f"Skipped: {status['reason']}", file=sys.stderr)
        return 3
    with httpx.Client(base_url=config.OLLAMA_URL, timeout=10) as ollama:
        ollama_version = ollama.get("/api/version").json().get("version")
        tags = ollama.get("/api/tags").json().get("models", [])
    model = next((m for m in tags if m.get("name") in (config.OLLAMA_MODEL, f"{config.OLLAMA_MODEL}:latest")), {})

    calls: list[dict] = []
    real_ask = ai_summary._ask

    def recording_ask(client, messages):
        started = time.perf_counter()
        content, parsed = real_ask(client, messages)
        calls.append({"seconds": round(time.perf_counter() - started, 1), "validJson": parsed is not None,
                      "content": content})
        return content, parsed
    ai_summary._ask = recording_ask

    started_at, results = now(), []
    with TestClient(app) as client:
        products = {}
        for name, case in CASES.items():
            response = client.post("/api/uploads/import", data={
                "product_name": f"AI eval: {name}", "domain": case["domain"],
                "columns": json.dumps({"text": "review", "rating": "stars", "id": "id"})},
                files={"file": (f"{name}.csv", case["text"].encode(), "text/csv")})
            products[name] = response.json()["id"]
        response = client.post("/api/uploads/import", data={
            "product_name": "AI eval: bundled sample", "domain": "product",
            "columns": json.dumps({"text": "review_text", "rating": "rating", "date": "review_date",
                                   "title": "review_title", "id": "review_id"})},
            files={"file": ("sample.csv", SAMPLE.read_bytes(), "text/csv")})
        products["bundled-sample"] = response.json()["id"]

        for name, product_id in products.items():
            before = len(calls)
            t0 = time.perf_counter()
            response = client.post(f"/api/products/{product_id}/ai-summary")
            seconds = round(time.perf_counter() - t0, 1)
            analysis = client.get(f"/api/products/{product_id}/analysis", params={"include_reviews": "false"}).json()
            body = response.json()
            entry = {"case": name, "http": response.status_code, "seconds": seconds,
                     "sentimentEngine": (analysis.get("engine") or {}).get("id"),
                     "analysedReviews": analysis["stats"].get("analysedReviews"),
                     "totalReviews": analysis["stats"]["totalReviews"], "calls": calls[before:]}
            if response.status_code == 200:
                run = analysis["analysisId"]
                from app.database import SessionLocal
                from app.models import AnalysisResult
                with SessionLocal() as db:
                    package = ai_summary.build_package(db.get(AnalysisResult, run), "")
                claims = {c["id"]: c for c in package["claims"]}
                excerpts = {e["id"]: e for c in package["claims"] for e in c["excerpts"]}
                entry |= {"status": body["status"], "attempts": body["attempts"], "problems": body["problems"],
                          "sentences": body["sentences"],
                          "review": [{"sentence": s["text"],
                                      "cites": [{"id": c, "statement": package["overview"]["statement"] if c == "O"
                                                 else claims.get(c, {}).get("statement")} for c in s["claims"]]
                                      + [{"id": e, "reviewId": excerpts.get(e, {}).get("reviewId"),
                                          "excerpt": excerpts.get(e, {}).get("text")} for e in s["excerpts"]],
                                      "label": None} for s in body["sentences"]]}
            else:
                entry |= {"status": "refused", "detail": body.get("detail")}
            results.append(entry)
            print(f"{name:24} {entry['status']:9} attempts {entry.get('attempts', '-')}  {seconds}s", flush=True)

    generated = [r for r in results if r["status"] in ("accepted", "rejected")]
    accepted = [r for r in generated if r["status"] == "accepted"]
    output = {
        "kind": "reviews-dekho-ai-overview-evaluation", "harnessVersion": HARNESS_VERSION, "appVersion": VERSION,
        "startedAt": started_at, "finishedAt": now(), "methodology": METHOD,
        "environment": {"platform": platform.platform(), "machine": platform.machine(),
                        "python": platform.python_version()},
        "model": {"name": config.OLLAMA_MODEL, "digest": model.get("digest"), "size": model.get("size"),
                  "ollamaVersion": ollama_version, "promptVersion": ai_summary.PROMPT_VERSION,
                  "options": {"temperature": 0, "seed": ai_summary.SEED, "num_predict": 600},
                  "format": "JSON schema", "maxAttempts": 2, "timeoutSeconds": config.OLLAMA_TIMEOUT_SECONDS},
        "summary": {
            "cases": len(results), "generated": len(generated), "accepted": len(accepted),
            "rejected": len(generated) - len(accepted), "refusedByDesign": len(results) - len(generated),
            "acceptanceRate": round(len(accepted) / len(generated), 3) if generated else None,
            "acceptedAtFirstAttempt": sum(r["attempts"] == 1 for r in accepted),
            "acceptedAfterRetry": sum(r["attempts"] == 2 for r in accepted),
            "acceptedSentences": sum(len(r["sentences"]) for r in accepted),
            "secondsPerOverview": stats([r["seconds"] for r in generated]),
            "secondsPerModelCall": stats([c["seconds"] for r in results for c in r["calls"]]),
            "invalidJsonAnswers": sum(not c["validJson"] for r in results for c in r["calls"]),
        },
        "manualReview": {"status": "not done",
                         "instructions": "For each accepted sentence in cases[].review, compare it with its cited "
                                         "claims and excerpts and set label to fully, partially or unsupported."},
        "cases": results,
    }
    out = Path(args.out) if args.out else BACKEND / "storage" / "ai_eval" / f"ai-overview-{started_at[:19].replace(':', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n")
    s = output["summary"]
    print(f"\n{s['accepted']} of {s['generated']} accepted ({s['rejected']} rejected, {s['refusedByDesign']} refused by "
          f"design); per overview {s['secondsPerOverview']}. Written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

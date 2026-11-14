"""The AI evaluation harness and its committed results (Phase 8): synthetic only, nothing invented."""
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RESULTS = BACKEND.parent / "docs" / "evaluation" / "ai_overview"
sys.path.insert(0, str(BACKEND / "scripts"))
import ai_eval_cases  # noqa: E402


def test_cases_are_synthetic_and_have_no_app_store_case():
    assert list(ai_eval_cases.CASES) == ["mostly-positive", "mostly-negative-app", "mixed", "conflicting-features",
                                         "very-small", "too-small", "unsupported-languages", "prompt-injection"]
    assert "apps.apple.com" not in Path(ai_eval_cases.__file__).read_text()


def test_missing_ollama_is_reported_and_nothing_is_written(tmp_path):
    out = tmp_path / "run.json"
    env = {"PATH": "/usr/bin:/bin", "HOME": str(Path.home()), "OLLAMA_URL": "http://127.0.0.1:9"}
    result = subprocess.run([sys.executable, "scripts/evaluate_ai_overview.py", "--out", str(out)], cwd=BACKEND,
                            capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 3
    assert "Skipped: The local Ollama server isn’t running" in result.stderr
    assert not out.exists()


def test_committed_runs_contain_no_real_review_text_and_no_invented_labels():
    historical = json.loads((RESULTS / "phase6-round4-historical.json").read_text())
    real = [c for c in historical["cases"] if c["source"] != "synthetic"]
    assert [c["case"] for c in real] == ["real-whatsapp-in", "real-zomato-in"]
    for case in real:   # numbers only
        assert not {"answers", "sentences", "problems", "review"} & set(case)
    assert historical["summary"]["accepted"] == 8 and historical["summary"]["generated"] == 10
    assert (historical["manualReview"]["fully"], historical["manualReview"]["partially"],
            historical["manualReview"]["unsupported"]) == (20, 4, 0)

    for path in RESULTS.glob("run-*.json"):
        run = json.loads(path.read_text())
        assert all(not c["case"].startswith("real-") for c in run["cases"])
        labels = [r["label"] for c in run["cases"] for r in c.get("review", [])]
        assert run["manualReview"]["status"] != "not done" or all(label is None for label in labels)
        assert run["model"]["digest"] and run["model"]["ollamaVersion"] and run["startedAt"]

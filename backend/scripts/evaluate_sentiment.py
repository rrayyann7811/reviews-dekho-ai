"""Evaluate the sentiment engines on human-labelled data, reproducibly.

Run from backend/:
    .venv/bin/python scripts/evaluate_sentiment.py              # labelled datasets only
    .venv/bin/python scripts/evaluate_sentiment.py --app-store  # + weak-label check on live App Store reviews

Writes docs/evaluation/results.json and docs/EVALUATION.md. Datasets are
downloaded once into backend/data/eval/ (git-ignored), pinned to exact files and
checked with SHA-256. Only computed numbers are written to docs/, never review text.

Engines compared
  vader-base   plain VADER, no review rules (the Phase 1-3 baseline minus its small lexicon)
  vader        VADER + review rules (app/nlp/rules.py) — the fallback engine
  transformer  cardiffnlp/twitter-roberta-base-sentiment-latest, int8 ONNX — the default engine

Evaluations
  E1  UCI Sentiment Labelled Sentences (Kotzias et al., 2015): 3,000 review sentences from Amazon,
      Yelp and IMDb, human-labelled positive/negative. Binary gold labels: a "neutral" prediction is
      counted as wrong, and the neutral rate is reported separately.
  E2  SemEval-2014 Task 4 test sets (Pontiki et al., 2014): laptop and restaurant review sentences
      with human-labelled sentiment per aspect term (positive/negative/neutral; "conflict" excluded).
      Measures the aspect method: the engine scores the clause containing the term ("clause"),
      compared with scoring the whole sentence ("sentence").
  E3  SentiMix Hindi-English dev set (SemEval-2020 Task 9): 3,000 code-mixed tweets with a
      human Hindi/English tag on every word. Measures (a) how often the language check flags
      Hindi-dominant text, (b) how often it wrongly flags English, (c) how badly the engines do on
      Hindi-dominant text — the reason such reviews are excluded.
  E4  (optional) Agreement with star ratings on live App Store reviews: 1-2 stars = negative,
      3 = neutral, 4-5 = positive. Stars are NOT ground truth; this is reported as weak-label agreement.
"""
import argparse
import hashlib
import io
import json
import platform
import resource
import sys
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402
from app.nlp.engines import TransformerEngine, VaderEngine  # noqa: E402
from app.nlp.language import NOT_SUPPORTED, detect_language  # noqa: E402
from app.nlp.preprocess import split_clauses, tidy_for_analysis  # noqa: E402
from app.nlp.sentiment import label_for  # noqa: E402

DATA = BACKEND / "data" / "eval"
DOCS = BACKEND.parent / "docs"
HF = "https://huggingface.co/datasets"
DATASETS = {
    "uci_sentences.zip": ("https://archive.ics.uci.edu/static/public/331/sentiment+labelled+sentences.zip",
                          "afc26626d710899948693e1a61405dce197f57ffa719fa1130d346b4cc095343"),
    "Laptops_Test_Gold.xml": (f"{HF}/alexcadillon/SemEval2014Task4/resolve/3fd43769112ef6517c263e303fbb7dc3002c35df/"
                              "ABSA_Gold_TestData/Laptops_Test_Gold.xml",
                              "aa3a30c9dd7e0eacf9b69e898eb4118a36c1b4f391a30a08dfc41a38d8b8745b"),
    "Restaurants_Test_Gold.xml": (f"{HF}/alexcadillon/SemEval2014Task4/resolve/3fd43769112ef6517c263e303fbb7dc3002c35df/"
                                  "ABSA_Gold_TestData/Restaurants_Test_Gold.xml",
                                  "f21509cfa37e16534cd5b2da043be487355b64ef48fe8d6aaacaeca6b49cc0fb"),
    "sentimix_dev.txt": (f"{HF}/RTT1/SentiMix/resolve/205f0391fc1f10320ec3c10708eaa27e88db04c7/dev_3k_split_conll.txt",
                         "e4dc583ed95e892669527b864aac01b86d990aee59d5fdc91a5e615e0f5f00a0"),
    "sentimix_test.txt": (f"{HF}/RTT1/SentiMix/resolve/205f0391fc1f10320ec3c10708eaa27e88db04c7/"
                          "Hindi_test_unalbelled_conll_updated.txt",
                          "3bfb1c33d2429db79e33a3eab0823e2c3597eada2afbbed5070468c8f4262fcd"),
    "sentimix_test_labels.txt": (f"{HF}/RTT1/SentiMix/resolve/205f0391fc1f10320ec3c10708eaa27e88db04c7/"
                                 "test_labels_hinglish.txt",
                                 "6ce8340f8c8b20e81cccb40265ebfcde00b4de0423651a0d7ebdd5a75fc884ed"),
}
LABELS3 = ["negative", "neutral", "positive"]
APP_STORE_SAMPLE = [  # (country, app id, name) — popular apps with many recent written reviews
    ("in", "310633997", "WhatsApp Messenger"),
    ("in", "434613896", "Zomato"),
    ("in", "989540920", "Swiggy"),
    ("us", "284882215", "Facebook"),
]


# ---------- data ----------

def fetch(name: str) -> bytes:
    url, expected = DATASETS[name]
    path = DATA / name
    if not path.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {name}", flush=True)
        response = httpx.get(url, follow_redirects=True, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise SystemExit(f"{name}: checksum mismatch ({actual}); delete it and run again")
    return content


def load_uci() -> list[dict]:
    rows = []
    with zipfile.ZipFile(io.BytesIO(fetch("uci_sentences.zip"))) as archive:
        for source in ("amazon_cells", "yelp", "imdb"):
            text = archive.read(f"sentiment labelled sentences/{source}_labelled.txt").decode("utf-8")
            for line in text.splitlines():
                sentence, _, label = line.rstrip().rpartition("\t")
                if sentence and label in ("0", "1"):
                    rows.append({"text": sentence.strip(), "gold": "positive" if label == "1" else "negative",
                                 "source": source})
    return rows


def load_semeval(name: str) -> list[dict]:
    rows = []
    for sentence in ET.fromstring(fetch(name)).iter("sentence"):
        text = sentence.findtext("text") or ""
        for term in sentence.iter("aspectTerm"):
            polarity = term.get("polarity")
            if polarity in LABELS3:  # "conflict" (both positive and negative) is excluded
                rows.append({"sentence": text, "term": term.get("term"), "gold": polarity,
                             "start": int(term.get("from")), "end": int(term.get("to"))})
    return rows


def clause_for(sentence: str, start: int, end: int, term: str) -> str:
    """The clause (as split by the app) that contains the aspect term — the app's aspect context."""
    offset = 0
    for clause in split_clauses(sentence):
        position = sentence.find(clause, offset)
        if position != -1:
            if position <= start and end <= position + len(clause):
                return clause
            offset = position
    return next((c for c in split_clauses(sentence) if term.lower() in c.lower()), sentence)


def load_sentimix(split: str = "dev") -> list[dict]:
    """dev: labels inside the file. test: labels in a separate CSV (uid,sentiment)."""
    labels = {}
    if split == "test":
        for line in fetch("sentimix_test_labels.txt").decode("utf-8").splitlines()[1:]:
            uid, _, label = line.strip().partition(",")
            labels[uid] = label
    tweets, words, previous = [], [], None
    for line in fetch(f"sentimix_{split}.txt").decode("utf-8").splitlines() + [""]:
        parts = line.split("\t")
        if parts[0] == "meta":
            words, previous = [], None
            gold = parts[2].strip() if split == "dev" else labels.get(parts[1].strip(), "")
            tweets.append({"gold": gold, "words": words})
        elif len(parts) == 2 and tweets:
            token, tag = parts[0].strip(), parts[1].strip()
            is_handle = previous == "@"
            previous = token
            if is_handle or token == "@" or token.startswith(("http", "//")) or "/" in token:
                continue
            words.append((token, tag))
    out = []
    for tweet in tweets:
        tags = [tag for _, tag in tweet["words"] if tag in ("Hin", "Eng")]
        if len(tags) < 3:
            continue
        out.append({"text": " ".join(t for t, _ in tweet["words"]), "gold": tweet["gold"],
                    "hindi_share": tags.count("Hin") / len(tags)})
    return out


# ---------- engines ----------

class VaderBase:
    id, name = "vader-base", "VADER, no review rules"

    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

    def predict(self, texts):
        return [{"label": label_for(self.analyzer.polarity_scores(t)["compound"])} for t in texts]


def benchmark(engine, texts, runs: int = 3) -> dict:
    """Throughput: one warm-up pass, then the median of `runs` timed passes over all texts."""
    prepared = [tidy_for_analysis(t) for t in texts]
    engine.predict(prepared[:64])
    times = []
    for _ in range(runs):
        started = time.perf_counter()
        engine.predict(prepared)
        times.append(time.perf_counter() - started)
    median = sorted(times)[len(times) // 2]
    return {"texts": len(texts), "runs": runs, "medianSeconds": round(median, 3),
            "textsPerSecond": round(len(texts) / median, 1)}


def timed_predict(engine, texts):
    started = time.perf_counter()
    predictions = [p["label"] for p in engine.predict([tidy_for_analysis(t) for t in texts])]
    return predictions, time.perf_counter() - started


# ---------- metrics ----------

def metrics(gold: list[str], predicted: list[str], classes: list[str]) -> dict:
    precision, recall, f1, support = precision_recall_fscore_support(
        gold, predicted, labels=classes, average=None, zero_division=0)
    return {
        "n": len(gold),
        "accuracy": round(accuracy_score(gold, predicted), 4),
        "macroF1": round(float(sum(f1) / len(classes)), 4),
        "perClass": {c: {"precision": round(float(p), 4), "recall": round(float(r), 4), "f1": round(float(f), 4),
                         "support": int(s)} for c, p, r, f, s in zip(classes, precision, recall, f1, support)},
        # Rows: gold labels. Columns: all three predicted labels (binary gold can still be predicted neutral).
        "confusion": {"rows (gold)": classes, "columns (predicted)": LABELS3,
                      "matrix": [[sum(1 for g, p in zip(gold, predicted) if g == gold_label and p == predicted_label)
                                  for predicted_label in LABELS3] for gold_label in classes]},
        "neutralPredictionRate": round(predicted.count("neutral") / len(predicted), 4) if predicted else 0,
    }


# ---------- evaluations ----------

def e1_uci(engines) -> dict:
    rows = load_uci()
    texts, gold = [r["text"] for r in rows], [r["gold"] for r in rows]
    result = {"dataset": "UCI Sentiment Labelled Sentences (Kotzias et al., 2015)", "size": len(rows),
              "labels": "human, binary (positive/negative)", "engines": {}}
    for engine in engines:
        predicted, _ = timed_predict(engine, texts)
        entry = metrics(gold, predicted, ["negative", "positive"])
        entry["bySource"] = {s: round(accuracy_score([g for g, r in zip(gold, rows) if r["source"] == s],
                                                     [p for p, r in zip(predicted, rows) if r["source"] == s]), 4)
                             for s in ("amazon_cells", "yelp", "imdb")}
        decided = [(g, p) for g, p in zip(gold, predicted) if p != "neutral"]
        entry["accuracyWhenNotNeutral"] = round(sum(g == p for g, p in decided) / len(decided), 4) if decided else None
        entry["speed"] = benchmark(engine, texts)
        result["engines"][engine.id] = entry
    return result


def e2_semeval(engines) -> dict:
    result = {"dataset": "SemEval-2014 Task 4 test sets (Pontiki et al., 2014)",
              "labels": "human, per aspect term, 3-class (conflict excluded)", "domains": {}}
    for domain, name in (("laptops", "Laptops_Test_Gold.xml"), ("restaurants", "Restaurants_Test_Gold.xml")):
        rows = load_semeval(name)
        gold = [r["gold"] for r in rows]
        inputs = {"clause": [clause_for(r["sentence"], r["start"], r["end"], r["term"]) for r in rows],
                  "sentence": [r["sentence"] for r in rows]}
        domain_result = {"size": len(rows), "goldDistribution": {c: gold.count(c) for c in LABELS3}, "engines": {}}
        for engine in engines:
            domain_result["engines"][engine.id] = {
                method: metrics(gold, timed_predict(engine, texts)[0], LABELS3) for method, texts in inputs.items()}
        result["domains"][domain] = domain_result
    return result


def e3_sentimix(engines, uci_rows, split: str) -> dict:
    tweets = [t for t in load_sentimix(split) if t["gold"] in LABELS3]
    groups = {"hindiDominant (≥50% Hindi words)": [t for t in tweets if t["hindi_share"] >= 0.5],
              "mixed (20–50%)": [t for t in tweets if 0.2 < t["hindi_share"] < 0.5],
              "englishDominant (≤20% Hindi words)": [t for t in tweets if t["hindi_share"] <= 0.2]}
    detection = {}
    for group, items in groups.items():
        flagged = sum(detect_language(t["text"])["status"] == NOT_SUPPORTED for t in items)
        detection[group] = {"tweets": len(items), "flaggedNotSupported": flagged,
                            "flaggedRate": round(flagged / len(items), 4) if items else None}
    english_flagged = sum(detect_language(r["text"])["status"] == NOT_SUPPORTED for r in uci_rows)
    sentiment = {}
    for group in ("hindiDominant (≥50% Hindi words)", "englishDominant (≤20% Hindi words)"):
        items = groups[group]
        sentiment[group] = {engine.id: metrics([t["gold"] for t in items],
                                               timed_predict(engine, [t["text"] for t in items])[0], LABELS3)
                            for engine in engines}
    return {"dataset": f"SentiMix Hindi-English {split} split (SemEval-2020 Task 9)", "split": split,
            "size": len(tweets),
            "labels": "human word-level language tags; human tweet sentiment (3-class)",
            "languageCheck": {"onSentiMix": detection,
                              "onEnglishUCI": {"sentences": len(uci_rows), "wronglyFlagged": english_flagged,
                                               "rate": round(english_flagged / len(uci_rows), 4)}},
            "engineSentimentByLanguage": sentiment}


def e4_app_store(engines) -> dict:
    from app.collectors.apple_app_store import AppleAppStoreAdapter
    from app.collectors.base import ProductRef
    from app.collectors.http import make_client
    from app.services.ingestion import clean_records

    config.APPLE_PAGE_DELAY_SECONDS = 0.5
    adapter, rows, apps = AppleAppStoreAdapter(), [], []
    with make_client() as client:
        for country, app_id, name in APP_STORE_SAMPLE:
            product = adapter.collect(ProductRef(adapter.id, app_id, country, ""), client)
            reviews, _ = clean_records(product.reviews)
            apps.append({"app": name, "country": country.upper(), "reviews": len(reviews)})
            rows += [r for r in reviews if r["rating"]]
    english = [r for r in rows if detect_language(r["text"])["status"] != NOT_SUPPORTED]
    flagged = len(rows) - len(english)
    star = {1: "negative", 2: "negative", 3: "neutral", 4: "positive", 5: "positive"}
    gold = [star[r["rating"]] for r in english]
    return {"dataset": "Live App Store reviews (weak labels from star ratings — NOT ground truth)",
            "collectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "apps": apps,
            "reviewsWithStars": len(rows), "englishReviewsUsed": len(english),
            "flaggedNotEnglish": flagged,
            "engines": {e.id: metrics(gold, timed_predict(e, [r["text"] for r in english])[0], LABELS3)
                        for e in engines}}


# ---------- report ----------

def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


METHODOLOGY = """## Methodology

**Label mapping.** Model: the config's `id2label` (0 negative, 1 neutral, 2 positive); the label is the most likely class.
VADER: compound ≥ 0.05 positive, ≤ −0.05 negative, otherwise neutral (the authors' thresholds). UCI: `0` negative,
`1` positive. SemEval-2014: the annotated `polarity` of each aspect term; `conflict` terms are excluded (laptops 16,
restaurants 14). SentiMix: the annotated tweet sentiment; word language from the `Hin`/`Eng` tags, ignoring `@handles`,
links and untagged tokens, and tweets with fewer than 3 tagged words. E4: 1–2★ negative, 3★ neutral, 4–5★ positive.

**Averaging.** Per-class precision, recall and F1 come from scikit-learn `precision_recall_fscore_support(average=None)`
with `zero_division=0`. Macro F1 is the unweighted mean of the per-class F1 over the **gold classes**: negative and
positive for E1; negative, neutral and positive for E2, E3 and E4. Accuracy is the share of exact matches.

{e1_explanation}

**Development / evaluation overlap (what influenced what).**
* *Model choice* was made before any evaluation data was downloaded, from documented properties (3-class, size,
  licence, usage). No evaluation result was used to choose it, and no alternative model was evaluated.
* *VADER review rules* came from hand-written probe phrases, not from evaluation data. One rule (verbs after "unable
  to") was widened after the first evaluation run because a hand-written unit test failed; E1/E2 results were not used
  to change rules or thresholds.
* *Feature context (clause vs sentence)* was designed before E2 and is reported both ways; nothing was tuned on E2.
* *Batch size 1* was chosen for determinism (results must not depend on other reviews), not for accuracy.
* *Language check*: the word lists are built from the SentiMix **train** split. The **dev** split was used during
  development: its first result (48% of Hindi-dominant tweets caught) led to the data-driven word list, so dev is a
  development set, not an unbiased test. The **test** split was used only for the final run reported above. The UCI
  English sentences were also watched for false alarms during development. Hand-added Hinglish spelling variants and
  the general English word list were added after reading reviews flagged in live App Store data from WhatsApp India
  and Zomato India — the same apps as E4 — so E4's "flagged as not English" count is not independent.
* *Pretraining*: the model was fine-tuned on tweets (not on UCI, SemEval or SentiMix), but its RoBERTa base was
  pretrained on large web corpora whose contents cannot be checked; overlap with public review text can't be ruled out.
* Thresholds (Hinglish: ≥ 2 words and ≥ 20%; other languages: ≥ 6 words and < 25% known English) were set before
  measuring and were not changed after."""


def e1_explanation(m: dict) -> str:
    (nn, nu, np_), (pn, pu, pp) = m["confusion"]["matrix"]
    neg, pos = m["perClass"]["negative"], m["perClass"]["positive"]
    return (f"**Why E1 macro F1 ({m['macroF1']:.3f}) is higher than accuracy ({pct(m['accuracy'])}).** E1's gold labels are "
            "binary but the engines can answer \"neutral\". A neutral answer is an error for accuracy and lowers the "
            "**recall** of the true class, but it is not a prediction of either gold class, so it never lowers "
            f"**precision**. Transformer: {nn:,} + {pp:,} = {nn + pp:,} of {m['n']:,} correct ({pct(m['accuracy'])}); "
            f"negative precision {pct(neg['precision'])}, recall {pct(neg['recall'])} (F1 {neg['f1']:.3f}); positive "
            f"precision {pct(pos['precision'])}, recall {pct(pos['recall'])} (F1 {pos['f1']:.3f}); mean {m['macroF1']:.3f}. "
            f"Because precision ignores the {nu + pu:,} neutral answers, E1 macro F1 flatters engines that answer neutral "
            "often. Compare engines on accuracy and the neutral rate, and read macro F1 together with them.")


def write_markdown(results: dict) -> str:
    lines = ["# Sentiment evaluation", "",
             f"_Generated by `backend/scripts/evaluate_sentiment.py` on {results['generatedAt']} "
             f"({results['machine']}). Do not edit by hand; re-run the script._", "",
             "Engines: **vader-base** = plain VADER; **vader** = VADER + review rules (fallback engine); "
             "**transformer** = `cardiffnlp/twitter-roberta-base-sentiment-latest`, int8 ONNX (default engine).", ""]
    e1 = results["E1"]
    lines += [f"## E1 — Sentence sentiment: {e1['dataset']}", "",
              f"{e1['size']} sentences, {e1['labels']}. A neutral prediction counts as wrong (gold has no neutral).", "",
              "| Engine | Accuracy | Macro F1 (neg/pos) | Neg P / R | Pos P / R | Neutral predictions | Accuracy when not neutral | Amazon / Yelp / IMDb acc. | Speed |",
              "|---|---|---|---|---|---|---|---|---|"]
    for engine_id, m in e1["engines"].items():
        n, p = m["perClass"]["negative"], m["perClass"]["positive"]
        lines.append(f"| {engine_id} | {pct(m['accuracy'])} | {m['macroF1']:.3f} | {pct(n['precision'])} / {pct(n['recall'])} | "
                     f"{pct(p['precision'])} / {pct(p['recall'])} | {pct(m['neutralPredictionRate'])} | "
                     f"{pct(m['accuracyWhenNotNeutral'])} | {' / '.join(pct(v) for v in m['bySource'].values())} | "
                     f"{m['speed']['textsPerSecond']:,.0f} texts/s |")
    e2 = results["E2"]
    lines += ["", f"## E2 — Aspect sentiment: {e2['dataset']}", "", f"{e2['labels']}.", "",
              "| Domain (n) | Engine | Context | Accuracy | Macro F1 | Neg F1 | Neu F1 | Pos F1 |", "|---|---|---|---|---|---|---|---|"]
    for domain, d in e2["domains"].items():
        for engine_id, methods in d["engines"].items():
            for method, m in methods.items():
                c = m["perClass"]
                lines.append(f"| {domain} ({d['size']}) | {engine_id} | {method} | {pct(m['accuracy'])} | {m['macroF1']:.3f} | "
                             f"{c['negative']['f1']:.3f} | {c['neutral']['f1']:.3f} | {c['positive']['f1']:.3f} |")
    e3, e3_dev = results["E3"], results["E3dev"]
    lc = e3["languageCheck"]
    lines += ["", f"## E3 — Hindi/Hinglish: {e3['dataset']}", "",
              f"{e3['size']} tweets, {e3['labels']}. **Untouched test split**: not used while building or adjusting the "
              f"language check. The development split's results are shown alongside for transparency (see Methodology).", "",
              "| Group | Test tweets | Flagged (test) | Dev tweets | Flagged (dev, used during development) |",
              "|---|---|---|---|---|"]
    for group, g in lc["onSentiMix"].items():
        d = e3_dev["languageCheck"]["onSentiMix"][group]
        lines.append(f"| {group} | {g['tweets']} | {pct(g['flaggedRate'])} | {d['tweets']} | {pct(d['flaggedRate'])} |")
    lines.append(f"| English review sentences (UCI) | {lc['onEnglishUCI']['sentences']} | {pct(lc['onEnglishUCI']['rate'])} "
                 "(false alarms) | | |")
    lines += ["", "Engine sentiment on the test tweets (3-class, human labels), showing why non-English text is excluded:", "",
              "| Group | Engine | Accuracy | Macro F1 |", "|---|---|---|---|"]
    for group, per_engine in e3["engineSentimentByLanguage"].items():
        for engine_id, m in per_engine.items():
            lines.append(f"| {group} | {engine_id} | {pct(m['accuracy'])} | {m['macroF1']:.3f} |")
    if "E4" in results:
        e4 = results["E4"]
        lines += ["", "## E4 — Agreement with star ratings (weak labels, NOT accuracy)", "",
                  f"{e4['englishReviewsUsed']} English App Store reviews with stars, collected {e4['collectedAt']} "
                  f"({', '.join(a['app'] + ' ' + a['country'] for a in e4['apps'])}); {e4['flaggedNotEnglish']} of "
                  f"{e4['reviewsWithStars']} were flagged as not English and left out. 1–2★ = negative, 3★ = neutral, "
                  "4–5★ = positive.", "",
                  "| Engine | Agreement | Macro F1 vs stars |", "|---|---|---|"]
        for engine_id, m in e4["engines"].items():
            lines.append(f"| {engine_id} | {pct(m['accuracy'])} | {m['macroF1']:.3f} |")
    lines += ["", f"Speed: median of 3 timed passes over the {e1['size']} E1 sentences after a warm-up, "
              f"batch size {results['transformer']['batchSize']}, 4 CPU threads. Model load: {results['transformer']['loadSeconds']} s. Peak memory of the whole "
              f"evaluation process: {results['peakMemoryMB']} MB."]
    lines += ["", METHODOLOGY.replace("{e1_explanation}", e1_explanation(results["E1"]["engines"]["transformer"]))]
    lines += ["", "Full numbers, including per-class precision/recall and confusion matrices: "
              "[`evaluation/results.json`](evaluation/results.json).", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-store", action="store_true", help="also measure agreement with live App Store stars")
    args = parser.parse_args()

    started = time.perf_counter()
    transformer = TransformerEngine()
    load_seconds = time.perf_counter() - started
    engines = [VaderBase(), VaderEngine(), transformer]

    print("E1 UCI sentences…", flush=True)
    e1 = e1_uci(engines)
    print("E2 SemEval-2014 aspects…", flush=True)
    e2 = e2_semeval(engines)
    print("E3 SentiMix Hinglish (test, then dev)…", flush=True)
    e3 = e3_sentimix(engines, load_uci(), "test")
    e3_dev = e3_sentimix(engines, load_uci(), "dev")
    results = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": f"{platform.machine()}, {platform.system()} {platform.release()}, Python {platform.python_version()}",
        "transformer": transformer.describe() | {"loadSeconds": round(load_seconds, 2),
                                                 "batchSize": config.MODEL_BATCH_SIZE},
        "E1": e1, "E2": e2, "E3": e3, "E3dev": e3_dev,
    }
    if args.app_store:
        print("E4 App Store weak labels…", flush=True)
        results["E4"] = e4_app_store(engines)
    # ru_maxrss is bytes on macOS, kilobytes on Linux.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    results["peakMemoryMB"] = round(rss / (1e6 if platform.system() == "Darwin" else 1e3))

    (DOCS / "evaluation").mkdir(parents=True, exist_ok=True)
    (DOCS / "evaluation" / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n")
    (DOCS / "EVALUATION.md").write_text(write_markdown(results))
    print(f"Wrote docs/EVALUATION.md and docs/evaluation/results.json in {time.perf_counter() - started:.0f}s")


if __name__ == "__main__":
    main()

# Reviews Dekho AI

Find out what customers think of a product from its reviews. Upload reviews as a CSV or Excel file, or paste an
App Store link, and the app works out the tone of each review, which features people praise or complain about, and
how the star ratings compare with what the reviews actually say.

Built with FastAPI, SQLite and SQLAlchemy (backend) and React, Vite and Tailwind (frontend).

## What works

| Input | Status |
|---|---|
| CSV / Excel (.xlsx) upload | ✅ Any website's reviews. Column detection, preview, cleaning (duplicates, empty rows, invalid ratings/dates). |
| Apple App Store app links | ✅ Up to the 500 most recent written reviews per country store, through Apple's public review feed. |
| Amazon, Flipkart links | ❌ Recognised, but not collected: their official APIs don't provide review text and their terms prohibit scraping. Upload an export instead. |
| Built-in demo product | ✅ Works offline, with clearly labelled synthetic reviews. |

Every analysis is stored as an unchanging snapshot in the history, together with the sentiment engine that produced it.
Each run has an **evidence-backed summary**: every claim states its exact counts and quotes up to three exact excerpts
from the reviews (by review ID), and a **PDF report** and CSV export can be downloaded for any run. An optional
**AI-written overview** can be produced by a local model through Ollama (off by default; see below).
Details, design decisions and verification results are in [`docs/PLAN.md`](docs/PLAN.md).

## Running it locally

Requirements: Python 3.10 or newer (developed and tested only on 3.14), Node 20.19 or newer (tested on 24).

```bash
# Backend
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/download_model.py   # optional, ~128 MB — see "Sentiment engines"
.venv/bin/uvicorn app.main:app --reload       # http://localhost:8000, API docs at /docs

# Frontend (second terminal)
cd frontend
npm install
npm run dev                                   # http://localhost:5173
```

If port 8000 is taken, start the backend with `--port 8765` and run the frontend with
`VITE_API_URL=http://localhost:8765/api npm run dev`. The database is created at `backend/storage/reviews_dekho.db`;
older databases are upgraded automatically on start, after a backup is copied to `backend/storage/backups/`.

## Sentiment engines

| Engine | Used when | What it is |
|---|---|---|
| **RoBERTa sentiment model** (default) | the model files are installed | [`cardiffnlp/twitter-roberta-base-sentiment-latest`](https://huggingface.co/cardiffnlp/twitter-roberta-base-sentiment-latest), a RoBERTa-base model fine-tuned for 3-class sentiment (negative / neutral / positive). Runs locally as an int8-quantized ONNX file with `onnxruntime`; no PyTorch and no internet connection needed after download. |
| **VADER** (fallback) | the model isn't installed or fails | The rule-based [VADER](https://github.com/cjhutto/vaderSentiment) lexicon with extra rules for review phrases ("keeps crashing", "can't log in", "no issues"). |

**Installing the model.** `backend/scripts/download_model.py` downloads three files (`onnx/model_quantized.onnx`,
`tokenizer.json`, `config.json`, ≈ 128 MB) from the Hugging Face repository
[`Xenova/twitter-roberta-base-sentiment-latest`](https://huggingface.co/Xenova/twitter-roberta-base-sentiment-latest),
pinned to revision `f3ec4d0925f90c3ca7ee7814f52d6ee7cf180445`. Each file is checked against the SHA-256 hash in the
script and only kept if it matches. They are saved to `backend/models/` (not committed to Git).

**How fallback works.** With `SENTIMENT_ENGINE=auto` (the default) the backend uses the model if its files and the
`onnxruntime`/`tokenizers` packages are available, and VADER otherwise. If the model fails during an analysis, the whole
run is redone with VADER, so a run never mixes engines. Every run records which engine was used and why it fell back,
and the analysis page shows it. `SENTIMENT_ENGINE=vader` always uses VADER.

## Reports

`GET /api/products/{id}/report.pdf?analysis_id=…` (or **Download PDF** on the analysis and Reports pages) builds an A4
report from one stored run: source and dates, key figures, sentiment and star-rating charts (vector), tone by star rating,
the evidence-backed summary with exact excerpts and review IDs, the feature table, the method with model attribution,
and limitations. It contains aggregates and a few excerpts, never the full review list, and **no reviewer names**. The
CSV export (`GET /api/products/{id}/report.csv?analysis_id=…`, or **Download CSV**) lists every review of that run
with its sentiment and features, and also leaves reviewer names out unless `include_reviewer=true` is added. Without
`analysis_id`, both use the latest run.

## Optional AI-written overview (local, off by default)

The backend can ask a **local** model to turn the evidence-backed summary into a short paragraph. No cloud or paid API
is used, and nothing is downloaded or started automatically.

```bash
ollama pull llama3.2:3b          # about 2 GB, once
ollama serve                     # in another terminal
AI_SUMMARIES=on .venv/bin/uvicorn app.main:app --reload
```

**Turning it off:** it is off unless `AI_SUMMARIES=on` (also `1`, `true`, `yes`) is set; start the backend without it
and the AI panel is hidden and the endpoint answers 409. Other settings: `OLLAMA_URL` (default
`http://127.0.0.1:11434`), `OLLAMA_MODEL` (default `llama3.2:3b`), `OLLAMA_TIMEOUT_SECONDS` (default 120). If Ollama
isn't running or the model isn't pulled, the endpoint says so (503) — the app never starts Ollama or downloads a model.

**Requirements (measured):** tested with Ollama 0.16.3 and `llama3.2:3b` on an Apple M3 Mac with 8 GB RAM. The model is
2.0 GB on disk and about 2.8 GB in memory while loaded (Ollama unloads it after 5 idle minutes). One overview took 6–49 s
(average 22 s) including a retry when needed; a single model call took 4–37 s. Running other heavy work at the same
time (e.g. the frontend test suite) slows both down noticeably on 8 GB.

The model receives only a structured evidence package (the stored claims with IDs, their exact excerpts and the overall
figures — no full reviews, no reviewer names) and must answer in JSON, citing claim and excerpt IDs for every sentence.
Settings are deterministic (temperature 0, fixed seed). A checker then rejects sentences that cite unknown evidence,
use numbers not in the cited claims, quote text that isn’t verbatim, mention uncited features, contradict a claim’s
direction or the overall tone, or generalise to “all customers”; the model gets one retry, and otherwise the attempt is
stored as rejected. The overview is always shown **below** the evidence-backed summary, labelled with the model, and
never replaces it; PDFs never include it.

**The checker is not a guarantee.** It catches detectable errors (wrong numbers, invented quotes, uncited features,
obvious contradictions). A sentence can pass every check and still be misleading — for example by emphasising a minor
point — so read the AI text together with the evidence it cites.

**Live results** (`llama3.2:3b`, final round, 11 test cases: synthetic product/app cases, a prompt-injection case,
non-English reviews, the bundled sample and two real App Store apps): one case had too few reviews and was refused by
design; of the other 10, **8 were accepted and 2 rejected** (5 accepted at the first attempt, 3 after the retry). Every
accepted sentence (24) was then checked by hand against the evidence it cites: **20 fully supported, 4 partially
supported, 0 unsupported**. The partial ones had correct numbers but drifted in meaning — e.g. calling a product
"mostly positive" when only the 8 English reviews (of 19) were analysed, attributing the overall star rating to "these
reviews", or describing "disappointment" while citing a positive excerpt. Rejections were for excerpt text pasted in
place of excerpt IDs and for a feature word ("camera performance") the checker treats strictly. The prompt-injection
reviews were not obeyed. Details: [`docs/PLAN.md`](docs/PLAN.md) (Phase 6).

## Limitations — read before relying on the results

* **English only.** Both engines understand only English. Reviews that look like Hindi, Hinglish (Hindi in Latin
  letters), another script or another language are marked **"Not analysed"**, left out of the sentiment percentages
  (their star ratings still count), and listed separately. Hinglish is *detected*, not analysed. Detection is a
  word-list heuristic: on an untouched test set it caught 87.7% of mostly-Hindi tweets with no false alarms on English
  review sentences, so some non-English text still gets through.
* **Accuracy.** On 3,000 human-labelled review sentences the model agreed with people 85.9% of the time (VADER: 69.5%);
  on feature-level labels for laptop and restaurant reviews, 76.8% and 78.9%. It was not measured on app reviews (no
  human-labelled set was available) and it can misread sarcasm. Full results and methodology:
  [`docs/EVALUATION.md`](docs/EVALUATION.md).
* **Features are found by keywords** (battery, camera, delivery… for products; login, crashes, ads… for apps). Features
  described in other words are missed, and two features in one clause joined by "and" share that clause's sentiment.
* **Long reviews** are judged on their first 256 tokens for the overall tone (features are judged clause by clause).
* **App Store** reviews are of apps, not physical products, and only the most recent 500 per country store are available.

## Tests

```bash
cd backend && .venv/bin/python -m pytest          # 361 tests; 10 need the sentiment model, 1 needs Ollama
cd frontend && npm test && npm run lint && npm run build   # 107 tests
```

With the sentiment model installed and Ollama running `llama3.2:3b`: 361 passed. With Ollama not running: 360 passed,
1 **skipped** (the live Ollama test). Without the sentiment model either: 350 passed, 11 skipped. Skipped tests are not
run. Frontend: 107 passed, lint clean, build OK. Re-run the sentiment evaluation with
`.venv/bin/python scripts/evaluate_sentiment.py --app-store`.

## Project layout

```
backend/app/
  api/          HTTP routes (thin)            services/    ingestion, analysis, collection, reports
  collectors/   one adapter per website       nlp/         engines, rules, language, aspects, keywords, summary
  models.py     database tables               migrations.py  versioned schema upgrades with backups
backend/scripts/  model download, evaluation, word-list builder, demo snapshot
frontend/src/     pages, components, lib (API client, formatting, filters)
docs/             PLAN.md (design + progress), EVALUATION.md (generated), DESIGN_SYSTEM.md
```

## Licences and attribution

* **Sentiment model**: `cardiffnlp/twitter-roberta-base-sentiment-latest` by Cardiff NLP, licensed
  [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). The ONNX file used here is a quantized conversion published
  by Xenova (`Xenova/twitter-roberta-base-sentiment-latest`, which names the Cardiff model as its base and states no
  separate licence); it is treated as a CC BY 4.0 adaptation of the original. Please cite:
  * D. Loureiro, F. Barbieri, L. Neves, L. Espinosa Anke, J. Camacho-Collados. *TimeLMs: Diachronic Language Models from
    Twitter.* ACL 2022 (System Demonstrations).
  * J. Camacho-Collados et al. *TweetNLP: Cutting-Edge Natural Language Processing for Social Media.* EMNLP 2022
    (System Demonstrations).
* **VADER**: C.J. Hutto and E. Gilbert, *VADER: A Parsimonious Rule-based Model for Sentiment Analysis of Social Media
  Text*, ICWSM 2014 (`vaderSentiment`, MIT licence).
* **Evaluation data** (downloaded by the scripts, never committed):
  [UCI Sentiment Labelled Sentences](https://archive.ics.uci.edu/dataset/331/sentiment+labelled+sentences)
  (Kotzias et al., KDD 2015; CC BY 4.0) · SemEval-2014 Task 4 aspect-based sentiment test sets (Pontiki et al., 2014;
  research use) · SentiMix Hindi-English, SemEval-2020 Task 9 (Patwa et al., 2020; Hugging Face mirror `RTT1/SentiMix`,
  listed as OpenRAIL). The Hinglish and English word lists in `backend/app/nlp/data/` are derived from the SentiMix
  training split.
* **PDF font**: [DejaVu Sans](https://dejavu-fonts.github.io/) 2.37 (Regular and Bold only), © Bitstream (Bitstream
  Vera licence) with DejaVu changes in the public domain. The full licence is in
  `backend/app/reports/fonts/LICENSE` and must stay with the font files.
* **Optional AI overview**: [Llama 3.2](https://www.llama.com/) 3B through [Ollama](https://ollama.com/), if you install
  it yourself; the model is subject to Meta's Llama 3.2 Community License. It is not bundled with this project.
* **App Store data**: reviews are read from Apple's public customer-review feed and stored only in your local database.

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
cd backend && .venv/bin/python -m pytest          # 273 tests; 10 of them need the model
cd frontend && npm test && npm run lint && npm run build   # 93 tests
```

With the model installed: 273 passed. Without it: 263 passed and the 10 model tests are **skipped** (not run).
Frontend: 93 passed. Re-run the sentiment evaluation with `.venv/bin/python scripts/evaluate_sentiment.py --app-store`.

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
* **App Store data**: reviews are read from Apple's public customer-review feed and stored only in your local database.

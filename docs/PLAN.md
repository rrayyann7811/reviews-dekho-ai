# Reviews Dekho AI — Implementation Plan (Phase 0)

_Prepared 2026-11-14. This is a living document; it will be updated as phases complete._

## 1. Workspace findings

| Item | Finding |
|---|---|
| Project folder | `~/Downloads/Reviews Dekho AI` exists and is **empty** — nothing to preserve or overwrite. |
| Git | There is **no repo for this project**. The folder is inside a Git repo whose root is the **home directory** (`~`), on branch `main`, with no commits and no remotes. |
| GitHub CLI | `gh` 2.104 is installed and logged in (HTTPS, keyring). No token needs to be shared. |
| Python | 3.14.3 (python.org build). Already installed globally: numpy, pandas 3, pydantic 2.12, SQLAlchemy 2.0, scikit-learn 1.8, reportlab, uvicorn, httpx. |
| Missing Python packages | fastapi, python-multipart, openpyxl, vaderSentiment, pytest, nltk, keybert |
| Node / npm | Node 24.13.1, npm 11.8.0 |
| Local LLM | Ollama 0.16.3 with `llama3` (8B) pulled; server not running. |
| Hardware | Apple M3, 8 cores, **8 GB RAM**, 86 GB free disk |

### Risks and how they're handled
1. **Home-directory Git repo.** If the project were committed through it, your whole home folder (`.zsh_history`, `.claude.json`, `.config`, etc.) could end up staged or pushed. The plan is to create a **separate repo inside the project folder** and leave the home-level repo untouched (you can decide about it later).
2. **8 GB RAM.** KeyBERT needs sentence-transformers and PyTorch (~2 GB download, high memory use). Llama3 8B needs about 5 GB while running. Both are heavy for this machine.
3. **Retrieving reviews from a URL.** Amazon and Flipkart don't offer a public review API, and their terms prohibit scraping. A working "paste an Amazon link and get its reviews" feature isn't possible without breaking the project's own rules. See §4.

## 2. Architecture

```
React (Vite, Tailwind, Recharts)  ──HTTP/JSON──►  FastAPI
                                                   ├─ api/        (routes only: validate → call service → respond)
                                                   ├─ services/   (business logic: products, ingestion, analysis, comparison, reports)
                                                   ├─ nlp/        (preprocess, sentiment, keywords, aspects, summary)
                                                   ├─ adapters/   (one per website; registry chooses by domain)
                                                   └─ db/         (SQLAlchemy models + session) ──► SQLite file
```

Design rules: routes stay thin, logic lives in services, the NLP package has no web or database code (so it's easy to unit-test), and every record carries a `source` field (`uploaded`, `demo`, `adapter:<site>`). The UI shows that source as a badge everywhere.

## 3. Folder structure

```
reviews-dekho-ai/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, CORS, routers, error handlers
│   │   ├── config.py          # settings from env vars
│   │   ├── database.py        # engine, session
│   │   ├── models.py          # Product, Review, AnalysisResult, Comparison, AnalysisHistory
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── api/               # products.py, uploads.py, analysis.py, compare.py, reports.py
│   │   ├── services/          # ingestion.py, analysis.py, comparison.py, reports.py
│   │   ├── adapters/          # base.py, registry.py, demo.py, (amazon.py/flipkart.py stubs → "unsupported")
│   │   └── nlp/               # preprocess.py, sentiment.py, keywords.py, aspects.py, summarizer.py
│   ├── data/sample/           # demo CSV/XLSX (synthetic, clearly labelled)
│   ├── tests/
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/        # ui/ (Button, Card, Table, Badge, EmptyState…), layout/, charts/
│   │   ├── pages/             # Overview, Analyze, Upload, History, ProductAnalysis, Compare, Reports, Settings
│   │   ├── lib/api.js         # single fetch wrapper
│   │   └── styles/
│   └── package.json
├── docs/ (PLAN.md, DESIGN_SYSTEM.md, screenshots/)
├── .gitignore
└── README.md
```

## 4. Key technical decisions

| Area | Decision | Reason |
|---|---|---|
| Sentiment | `vaderSentiment` (lexicon/rule-based, **not** deep learning) | Lightweight, fits short reviews, lexicon is bundled so nothing extra to download. |
| Keywords | scikit-learn n-gram TF-IDF/frequency with stopword filtering, instead of KeyBERT | Avoids PyTorch on 8 GB RAM and is simple to explain in a viva. |
| Aspects | Aspect lexicon (battery, camera, display…) + sentence splitting + VADER on the sentences that mention each aspect → positive/negative/mixed | Honest, transparent method, documented as rule-based. |
| Summaries | A grounded summary built by code from the analysis numbers and real quoted reviews is the default (always works). Ollama is an **optional** layer, labelled "AI-generated" and given only the computed facts and quotes. | Works offline and never invents content. The LLM is a bonus. |
| URL engine | Adapter registry. The URL is validated and the site/product ID detected. A **Demo adapter** works end to end. Amazon/Flipkart adapters recognise the URL but return a clear "retrieval not permitted, upload a CSV/export instead" message. | Follows the "no bypassing" rule; new adapters (e.g. a licensed data provider API) can be added later. |
| NLTK | Dropped unless needed: scikit-learn already provides stopwords, and VADER is standalone | Fewer dependencies and no corpus downloads. |
| Python env | Project-local `backend/.venv` | Keeps the global Python 3.14 clean. |

## 5. Dependencies to install (pending approval)

**Backend (`backend/.venv`):** fastapi, uvicorn[standard], pydantic, sqlalchemy, pandas, numpy, openpyxl, python-multipart, vaderSentiment, scikit-learn, reportlab, httpx, pytest
**Frontend (npm):** react, react-dom, react-router-dom, recharts, lucide-react; dev: vite, @vitejs/plugin-react, tailwindcss, @tailwindcss/vite, vitest, @testing-library/react, jsdom
**Optional:** Ollama `llama3` (already downloaded) or a smaller model such as `llama3.2:3b` (~2 GB download).

## 6. Milestones

| # | Phase | Done when |
|---|---|---|
| 0 | Inspection & plan | This document is approved |
| 1 | Design system + frontend shell, all pages, demo mode | Every route renders, layout tested at 375/768/1440 px |
| 2 | FastAPI, models, schemas, CRUD, Swagger, **CSV/XLSX ingestion with column detection and preview** (moved up from Phase 3), history, frontend wired to the API | ✅ Done 2026-11-14 |
| 3 | URL adapters (permitted sources only), richer demo dataset | Upload → preview → import already works; adapters remain |
| 4 | NLP engine | Unit tests on positive/negative/neutral/mixed cases pass |
| 5 | Analytics dashboard wired to the API | All charts/filters use backend data |
| 6 | Grounded summaries (+ optional Ollama) | Summaries cite counts and real quotes |
| 7 | Comparison | Side-by-side view with sample-size caveats |
| 8 | QA, README, screenshots, GitHub | Tests green, push only after your confirmation |

## 7. Progress log

**2026-11-14 — Setup + Phase 1 complete**
- Independent Git repo in the project folder (no commits yet); home-directory repo untouched.
- `backend/.venv` with pinned `requirements.txt`; frontend on Vite 8 / React 19 / Tailwind 4 / Recharts 3.
- Decisions recorded: KeyBERT optional (not installed), no LLM/Ollama for now, grounded summaries only.
- The core NLP modules (`backend/app/nlp/`) were written early so the demo analysis is real pipeline
  output, not hardcoded numbers. Phase 4 will add tests and refine them.
- Temporary: `frontend/src/demo/demoAnalysis.json` + `backend/scripts/build_demo_snapshot.py`
  are removed in Phase 5 when the frontend reads live API data.
- Frontend site detection (`src/lib/sites.js`) gives instant feedback; in Phase 3 the backend
  adapter registry becomes the source of truth.

**2026-11-14 — Phase 2 complete (backend + frontend integration)**

Phase 1 was committed locally first (`feat: complete Reviews Dekho AI frontend`). Nothing has been pushed.

*Backend layout*
```
backend/app/
├── main.py        app factory, CORS, routers, lifespan (creates tables)
├── config.py      env-driven settings (DATABASE_URL, CORS_ORIGINS, upload limits)
├── database.py    engine, session dependency, SQLite foreign keys ON
├── models.py      Product 1─< Review, Product 1─< AnalysisResult (cascade delete)
├── schemas.py     Pydantic models, camelCase JSON to match the frontend
├── errors.py      every error body is {"detail": "<readable message>"}
├── api/           health, products, reviews, uploads, history (thin routes)
├── services/      ingestion, analysis (wraps app/nlp unchanged), products, sites, reports
└── nlp/           unchanged from Phase 1
```
*Database*: three tables. Per-review results (sentiment, score, aspects) live on `reviews` and reflect the latest
run; product-level results (stats, aspects, keywords, summary, upload cleaning report) are stored per run in
`analysis_results`, so history keeps earlier runs. SQLite file: `backend/storage/reviews_dekho.db` (git-ignored).

*Endpoints* (Swagger at `http://localhost:8000/docs`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | API + database check |
| GET / POST | `/api/products` | List (with latest analysis numbers) / create empty product |
| GET / PATCH / DELETE | `/api/products/{id}` | Read / rename / delete (cascades) |
| GET | `/api/products/{id}/analysis` | Full latest analysis (same shape as the demo JSON) |
| POST | `/api/products/{id}/analyze` | Re-run analysis → new history entry |
| GET / POST | `/api/products/{id}/reviews` | List with sentiment/rating/search/paging filters / add reviews (re-analyses) |
| DELETE | `/api/products/{id}/reviews/{reviewId}` | Delete one review (re-analyses) |
| POST | `/api/uploads/preview` | Read CSV/XLSX, detect columns, sample rows, warnings; saves nothing |
| POST | `/api/uploads/import` | Clean + store + analyse → product |
| GET | `/api/products/{id}/report.csv` | Reviews with sentiment/features (formula-injection safe) |
| GET | `/api/products/{id}/report.pdf` | Returns 501 — not built yet |
| POST | `/api/products/from-url` | Recognises Amazon/Flipkart/demo/other links; always explains why it can't collect (422) |
| GET / DELETE | `/api/history`, `/api/history/{id}` | Every analysis run, newest first; detail; delete one run |

*Upload validation and cleaning*: .csv/.xlsx only, 10 MB, 20,000 rows; UTF-8/BOM/Windows-1252; comma,
semicolon, tab or pipe delimiters; blank rows and empty unnamed columns dropped; text whitespace-normalised and
capped at 5,000 chars; empty text skipped; duplicates skipped (same ID, or same text if no ID column);
ratings parsed from `4`, `4.0`, `4/5`, `4.5 stars` (out of range → "not given"); dates parsed day-first unless
ISO. Every skip/repair is counted in the stored `ingestion` report. A failed import leaves no partial data.

*Frontend changes (minimal, no redesign)*: Reports page — CSV download wired; PDF and demo-product export show
honest "not available" messages instead of broken links. `manual` source badge added. Demo-data comment updated.
Everything else (History, Overview, Upload, product analysis, URL form) already called these endpoints and now
receives real data. Demo mode is unchanged and still works with the server off.

*Verification*: backend `pytest` 81 passed · frontend `vitest` 43 passed (31 existing + 12 new
communication tests) · `oxlint` clean · `vite build` OK. Live run (uvicorn + `vite preview`): CORS preflight
from the frontend origin accepted; importing `demo_kestrel_orbit_5g.csv` through the API produced stats,
aspects, keywords and summary identical to the frontend's demo snapshot; XLSX import, invalid file (415),
history, CSV export and Swagger all checked.

*Not done / carried forward*
- PDF report (Phase 6/8), side-by-side comparison (Phase 7), URL adapters for permitted sources (Phase 3).
- The UI has no buttons yet for deleting/renaming products or adding single reviews; the API supports them.
- Re-analysis is synchronous; fine for the 20,000-row limit, a background job would be needed beyond that.
- No Alembic migrations: tables are created on startup. Schema changes during development mean deleting
  `backend/storage/reviews_dekho.db`.

*Run it*
```
cd backend && .venv/bin/uvicorn app.main:app --reload     # API on :8000, docs at /docs
cd frontend && npm run dev                                   # UI on :5173
cd backend && .venv/bin/python -m pytest                     # backend tests
```

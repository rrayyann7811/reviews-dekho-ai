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
| 2 | FastAPI, models, schemas, CRUD, Swagger | Endpoints pass TestClient tests |
| 3 | Adapters, CSV/XLSX ingestion with column detection and preview, demo dataset | Upload → preview → import works end to end |
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

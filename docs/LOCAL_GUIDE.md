# Local installation and demonstration

This is the full React/FastAPI application, separate from the synthetic GitHub Pages demo. No cloud account, API key, Docker, worker service or scheduler is needed. Local mode is a single workspace restricted to loopback requests; it is not a multi-user login system. Optional JWT owner isolation is covered separately by backend tests.

## Install once

Use macOS Apple Silicon, Python 3.12 or 3.14 and Node 24/npm. Start at the repository root in every new terminal. Python dependencies and model files may require a network download during installation; inference stays local.

```sh
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/download_model.py
```

The downloader verifies the pinned weights, tokenizer and configuration; valid installed files are reused. The model is approximately 122 MiB, and does not require PyTorch. An installation/model failure must be resolved before claiming ONNX is working: VADER fallback is a valid alternative engine, not proof of transformer inference.

In a second terminal:

```sh
cd frontend
npm ci
```

Do not replace an existing backend virtual environment unnecessarily. If it is already installed, use its Python and run the consistency check instead. Do not migrate, reset, seed or delete either existing application SQLite database for a rehearsal.

## Start a safe synthetic rehearsal

Backend terminal, from repository root:

```sh
cd backend
LOCAL_DATA_DIR="$(mktemp -d "${TMPDIR:-/tmp}/reviews-dekho-local.XXXXXX")" || exit 1
[ -n "$LOCAL_DATA_DIR" ] && [ -d "$LOCAL_DATA_DIR" ] || exit 1
export DATABASE_URL="sqlite:///$LOCAL_DATA_DIR/reviews.db"
export AUTH_MODE=local SENTIMENT_ENGINE=auto AI_SUMMARIES=off
printf 'Rehearsal database directory: %s\n' "$LOCAL_DATA_DIR"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Keep the printed directory for the session. This creates a **new** synthetic-workspace SQLite database, not `backend/storage/demo.db` or `backend/storage/reviews_dekho.db`. If `mktemp` fails or prints no directory, stop before starting the API. No account sign-in is required. The backend environment example is reference only: the app does not automatically load `.env` files. Avoid `--reload` for a memory-constrained demonstration; restart the backend explicitly after code/config changes.

Frontend terminal, from repository root:

```sh
cd frontend
VITE_AUTH_MODE=local VITE_API_URL=http://127.0.0.1:8000/api npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open `http://127.0.0.1:5173`. API health: `http://127.0.0.1:8000/api/health`. Interactive API documentation: `http://127.0.0.1:8000/docs`. Health verifies database connectivity, not model loading. A product's analysis engine metadata must identify the transformer after an import. Vite serves SPA routes on refresh; a generic static file server needs a fallback to `index.html`.

Both terminals stay in the foreground. Start the backend before uploading. Defaults allow both localhost/127.0.0.1 origins at 5173/4173; keep browser/API addresses consistent. If ports are occupied, stop your own prior servers or choose ports and explicitly adjust `VITE_API_URL`/`CORS_ORIGINS`; do not kill unknown processes.

## Stop and resume

Press **Ctrl+C in each server terminal**, and wait for backend shutdown. No always-on analysis worker or retention scheduler starts with either command. To resume stored results, restart the backend in the **same terminal with the same exported DATABASE_URL**; do not run `mktemp` again. In a new terminal, explicitly export the previously printed SQLite path before starting. Analyses are committed to that file and reloaded without inference. Temporary directories can be removed by macOS/reboot: they are for rehearsal, not durable archival storage.

For a new long-lived personal workspace, choose a new private directory and explicit SQLite URL outside the two protected database paths. Keep copies of your own data/backups, and review any schema-upgrade request separately; startup refuses outdated schemas. Never reset or migrate an existing file just to make a demonstration start. User-controlled process shutdown does not delete the database. Do not delete a rehearsal directory until both servers are stopped and you have checked that it is the synthetic directory you created.

## Demonstration walkthrough

1. Open Overview. The built-in fictional example can be explored even when the API is unavailable; it does **not** establish backend connectivity. Check health and import a new product to show the real path.
2. Open Upload reviews. Select a synthetic CSV from `backend/data/sample/` or `backend/data/demo/`. Preview rows, confirm the review-text/rating columns and give the product a clear synthetic name. Choose physical product versus app features, then **Import and analyse**.
3. Check the resulting product page: engine, analysed count, sentiment, ratings, charts, keyword/aspect panels and exact evidence. Switch to review filters and feature analytics. Small samples may correctly omit summary claims.
4. Repeat with an XLSX containing equivalent synthetic columns, saved as `.xlsx` (not `.xls`). The backend regression suite creates a real workbook with openpyxl; browser validation uses a generated synthetic workbook when recorded.
5. Open the product analysis directly, refresh the browser and restart the backend against the same rehearsal URL. Stored run IDs/counts should remain stable. Reanalysis deliberately creates a new snapshot.
6. Open Reports, select the imported product/run and download PDF and CSV. Open the PDF to inspect charts/method notes; check CSV contents. Downloads can contain private review text even though reviewer names are omitted by default.
7. Try a text file, corrupt workbook or header-only CSV. Expect a readable error and no imported partial product. Blank/unsupported-language reviews are reported rather than fabricated sentiment.
8. Optional: compare two imported products or two snapshots. Sample confidence intervals are descriptive, not proof that one product is better.

App Store collection depends on Apple's availability and network access; it is not required for an offline presentation. Amazon/Flipkart scraping is not supported. AI-written Ollama summaries are optional and off; the standard evidence/count summary works without an LLM.

## Screenshot checklist

Capture only synthetic data: Overview after import; upload preview/mapping; product sentiment/rating charts; Battery/Camera aspects and evidence; review filtering; saved history; comparison; PDF/CSV report; a readable invalid-file error; narrow-screen navigation. Use the actual application, include engine metadata where possible, and distinguish existing historical screenshots from this session's evidence. Do not overwrite the protected static-demo bundle to make screenshots.

## Limitations and troubleshooting

- English-only language heuristics and keyword aspects can miss sarcasm, paraphrases and mixed-language reviews. Transformer truncates at 256 tokens; batch one and four runtime threads remain unchanged. Sentiment is model output, not ground truth; neutral/negative disagreements should be inspected, not hardcoded away.
- On an 8 GiB Mac, run one API process and small rehearsal files first. Measured history-heavy API operational RSS was about 542 MiB and worker lifetime about 470 MiB, with larger temporary peaks. Close unrelated workloads; do not run ONNX benchmarks or Ollama concurrently just for the demo. See [performance limitations](ONNX_PERFORMANCE.md).
- Imports, collection and explicit reanalysis are synchronous. Keep the page open for the loading state. A separate opt-in job API exists for stored reviews, but the dashboard does not automatically start a worker. No background service is necessary for normal uploads.
- `Can’t reach the analysis server`: check backend terminal, health URL, Vite API environment and loopback address. Restart Vite after environment changes. A hosted sign-in screen locally usually means `VITE_AUTH_MODE` was overridden; start with the explicit local command.
- `Local mode only accepts loopback clients`: connect directly through 127.0.0.1/localhost, not LAN IP or forwarded proxy. Do not disable that restriction.
- VADER engine when ONNX was expected: verify pinned files with the downloader and inspect fixed fallback metadata. Restart the backend after restoring files because model-load failures are cached. No model API key is needed.
- Outdated-schema error: stop, confirm DATABASE_URL and use a fresh rehearsal path. Preserve the old file; migration requires a separately reviewed backup/upgrade procedure.
- HTTP 429: wait for Retry-After and avoid repeated clicks. Rate limits and single-expensive-operation admission stay enabled. A busy job can also hold database locks; no persistent worker is needed here.
- Empty/header-only files and invalid workbooks are rejected. Only CSV and modern XLSX are supported. PDFs use bundled fonts; unsupported emoji/scripts may be replaced with markers. Inspect the resulting PDF before presenting.
- Backend install failure: use the documented Python versions and the project virtual environment. Frontend install failure: verify Node 24. Do not mix globally installed Python packages with `.venv`.

## Bounded validation

These tests use disposable SQLite databases and synthetic reviews. No HTTP servers, cloud resources, Docker or persistent worker loop are required:

```sh
# From backend/
.venv/bin/python -m pytest -q tests/test_local_workflow.py tests/test_transformer_engine.py tests/test_jobs.py tests/test_auth.py tests/test_uploads.py tests/test_reports_pdf.py
.venv/bin/python -m pytest -rs
# From frontend/
npm test
npm run lint
npm run build
npm run check:app-bundle
npm run build:demo
npm run check:demo-bundle
```

`test_local_workflow.py` uses real model inference for CSV/XLSX import, all three sentiment classes, aspect output, persisted readback, PDF/CSV and a finite queued-to-succeeded job. One controlled inference exception verifies the supported whole-run VADER fallback. Existing job tests use controllable failures/clocks to verify running, retries/exhaustion, cancellation, interruption, fencing and rollback. They do not imply a persistent worker was activated. Model tests skip when weights are absent; PostgreSQL and live Ollama tests need their separately configured services. A green unit suite alone does not establish browser end-to-end readiness; see [actual local release verification](LOCAL_RELEASE_VERIFICATION.md).

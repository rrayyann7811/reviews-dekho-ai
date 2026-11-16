# Local release verification

Date: 2026-11-16. Base: `8d091eaba994509420d8436f8dbb84cbff5a9065`, branch `main`. This is a local-first final-year project review, not a deployment checkpoint. The existing uncommitted deployment architecture document is preserved without further edits.

## Actual checks completed

Environment: macOS Apple Silicon; 8 GiB host from the existing audit; Python 3.14.3, Node 24.13.1, npm 11.8.0. Installed Python dependencies pass `pip check`. All three installed ONNX/tokenizer/config files match the pins in `backend/scripts/download_model.py`. No model download or benchmark matrix was repeated. No production model settings changed.

| Workflow | Actual evidence and result |
|---|---|
| Real CSV and XLSX analysis | Four new model-integration test cases pass. Upload preview/import uses actual FastAPI routes, real pandas/openpyxl parsing, the pinned ONNX runtime and disposable SQLite. No mocked API responses. |
| Sentiment and features | Both formats yield one positive, one neutral and one negative synthetic review; Battery and Camera aspect aggregates are present. Model metadata is transformer with no fallback reason. |
| SQLite persistence | A new app/TestClient reads committed snapshots, same analysis ID/statistics and history reviews. This verifies a fresh application/client instance, not a separate OS-server restart. |
| Reports | Both formats generate real PDF bytes beginning `%PDF-` and CSV exports with all three reviews. Existing PDF tests verify content/layout primitives; browser downloads are verified below. Full page-by-page PDF visual inspection is not claimed. |
| Real-model job execution | Job creation returns queued; one finite `run_once` call produces succeeded with transformer metadata, and a subsequent finite poll finds no work. No always-on worker. |
| Failure fallback | A controlled model `predict` exception during actual import exercises whole-run VADER fallback, records fallback metadata and analyses all three reviews. No claim to reproduce kernel OOM recovery. |
| Failed/retried/interrupted jobs | Existing deterministic job tests exercise actual SQLite transactions, claim/running state, rollback, retry availability/exhaustion, queued cancellation, fencing and recovery. Controlled analysis failures/clocks are intentional; not every retry case uses ONNX. |
| Authentication/isolation | Existing signed-JWT tests verify owner-scoped access, foreign-owner rejection and local loopback restriction. Local mode itself is one workspace, not multi-user sign-in. No live Supabase service accessed. |
| Invalid/empty uploads | Existing upload/security tests pass for malformed CSV/XLSX, unsupported formats, empty/header-only datasets and rejection atomicity. |
| Frontend configuration | API client defaults to `http://localhost:8000/api`; local guide explicitly pairs 127.0.0.1 endpoints. No hardcoded production API origin found in the API client. Vite BrowserRouter refresh is verified in the completed browser checks below. |

## Validation results

- Focused real-model local workflow + durable jobs + authentication: **95 passed**.
- Full backend: **677 passed, 28 skipped**, 48.15 seconds. PostgreSQL/live Ollama integrations are not enabled. The four new workflow cases ran with the installed model.
- Frontend: **242 passed**, 16 test files. These existing component tests do not establish live browser/API integration.
- Frontend lint, production build, demo build and both bundle checks: passed.
- `git diff --check`, documentation local-link checks and protected-file checks: passed.

Logs are local temporary artifacts under `/private/tmp/reviews-local-{focused,backend,frontend,lint,build,app-bundle,demo,demo-bundle}.log`; none is part of the checkpoint. The test fixture overwrites DATABASE_URL with a throwaway SQLite target before application imports. No existing application database is migrated, reset or seeded.

## Confirmed issues and changes

The README incorrectly described authentication/rate limits/durable jobs as absent and cited obsolete test counts without distinguishing historical results. It also encouraged default application-database startup for rehearsal. Documentation now provides explicit loopback commands with a new rehearsal database, safe stop/resume instructions, honest feature status, an environment reference, screenshots checklist, troubleshooting and a demo walkthrough. No production runtime/UI defect was confirmed by the bounded tests, so no speculative application rewrite was made.

## Completed: real browser and network-server validation

User-approved temporary servers ran strictly on `127.0.0.1:8000` (FastAPI) and `127.0.0.1:5173` (Vite), with supported local authentication and a newly created disposable SQLite file outside the repository. Both ports were checked free beforehand. A temporary headless Chrome profile used a debugging pipe, not another listening application server. No API mocking or fake network responses were used; file uploads used the browser's actual file input. Completion recorded at 2026-11-16 02:36 UTC.

| Browser check | Actual result |
|---|---|
| Dashboard and connection | Overview loaded; server-connected state and real health response verified. Imported synthetic products appeared in the dashboard. |
| CSV and XLSX file inputs | Selected each real synthetic file in the browser, verified three-row preview and detected text/rating mappings, named the products, then imported through the normal UI. Two separate product records were created. |
| Actual ONNX | Both stored runs report transformer, no fallback, and one positive/one neutral/one negative review. Visible UI percentages are 33.3% each. Battery/Camera each have two mentions, one positive and one negative; insufficient-evidence labels are appropriate for this small sample. |
| Loading states | DOM observation recorded both “Reading file…” and “Analysing…” during the CSV flow without intercepting or altering API responses. |
| Charts/navigation | Desktop sentiment/rating charts rendered; aspect/keyword page and review list opened. Desktop chart/error screenshots and a narrow-screen feature screenshot were visually inspected. |
| Mobile | At 375 px, the navigation drawer opened and navigated back to Overview; imported products remained visible. No page-level horizontal overflow was observed. Wide aspect tables retain their internal horizontal scroll. |
| Route refresh | Actual page reload created a fresh browser document and rendered the product/charts again. Review-tab deep linking also remained usable. |
| PDF and CSV downloads | Clicked both Reports download buttons for the stored CSV product. Browser recorded two completed downloads: PDF 48,270 bytes with valid header/trailer; CSV 459 bytes with three rows and positive/negative/neutral labels. This verifies actual downloads, not full visual inspection of every PDF page. |
| Invalid/empty files | Unsupported `.txt` rejected in the UI; header-only CSV and corrupt XLSX produced readable backend-backed errors. The two expected preview HTTP 400 responses were negative-test outcomes; product count stayed two. |
| API restart/persistence | Stopped API process 58670, started process 59289 against the same disposable file, then loaded the product in the browser. Stored analysis ID 1 and statistics were unchanged. |
| Reanalysis after restart | Used the confirmation UI; real ONNX computation created analysis ID 3 while keeping the prior snapshot. |
| Console/network | Zero recorded JavaScript exceptions, console errors or browser log errors; no unexpected network destinations. Runtime API/asset traffic stayed on the two approved loopback origins. |

Final disposable database state before cleanup: two products, six original reviews, three analysis snapshots and zero processing jobs. Browser data was synthetic only. No permanent worker, retention scheduler, cloud service, Docker or deployment was started. No application defect was discovered, so no runtime/frontend/model code was changed during this browser verification. Test-controller locator/reload timing issues were corrected in temporary tooling only; they were not application failures.

Both application servers and the temporary browser were stopped, and owned process IDs/groups were checked absent. Ports 8000 and 5173 were released. The session's disposable DB, generated files/downloads, browser profile, screenshots, logs and controller were removed after recording these results. All ten protected demo files and both existing application SQLite databases retain their approved SHA-256 hashes. The pre-existing deployment architecture document remains byte-identical to the local-release safety snapshot. Nothing staged, committed or pushed.

Readiness: **ready for the complete core local demonstration described in LOCAL_GUIDE.md**, using small synthetic files on this Mac. English-only/model limitations, minimum evidence thresholds, synchronous large uploads and optional Ollama/App Store dependencies remain. This session did not validate all languages, maximum input sizes, external collection/email services, hosted deployment or long-duration production operation. No Linux memory-limit claim is made.

The previous full validation remains **677 backend passed / 28 skipped**, **242 frontend passed**, with lint, both builds and bundle checks passed. Only this verification record changes after the browser checks, so no redundant full suite/build rerun is claimed. Protected hashes, document links and `git diff --check` are checked again after cleanup.

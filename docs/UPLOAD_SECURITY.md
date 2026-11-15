# Phase 2C.1: upload security and resource limits

This is a local ingestion hardening checkpoint. No deployment, cloud resource, scheduler, external queue or
rate-limiting service is activated. The GitHub Pages synthetic demo and its frontend are unchanged.

## Audit and implemented boundaries

Previously the upload endpoint read at most 10 MiB plus one byte, but only after multipart parsing. CSV and
XLSX parsers materialized whole tables before checking 20,000 rows. There were no column, CSV field or ZIP
expansion budgets; parser errors could include source details. Review cleaning already truncated long text,
request dependencies closed database sessions, and ownership/expiry checks protected product operations.
Apple collection already had fixed source adapters, timeouts and at most ten pages of fifty reviews per fetch.

The API now authenticates before body processing, checks declared and actual body bytes before multipart
parsing, and rejects compressed HTTP request bodies. A missing or forged Content-Length does not bypass the
actual-byte check. Oversized/disconnected input never reaches multipart parsing. The bounded body is buffered
in memory; this is not a streaming-to-disk upload implementation. Multipart/file and parser copies add memory
above the wire-byte limit. Request timeouts and connection/header limits still belong at the reverse proxy.

The single-process middleware admits at most the configured number of concurrent POST/PUT/PATCH/DELETE
requests, including preview, import, collection, refresh, reanalysis and optional AI requests. Each verified
owner also has at most one mutating request in flight, even if the global limit is increased. Excess work gets
429 with Retry-After: 5. Admission is released on completion/failure/cancellation. Parsing and import/analysis
work run in the existing thread pool, keeping the event loop available. No background job queue is added.

## Environment settings

All values below are positive integers, read at backend startup. Invalid/nonpositive values fail startup.
Byte settings use bytes, character settings use Python string characters, and row counts exclude the header.

| Variable | Default | Meaning |
|---|---:|---|
| MAX_REQUEST_BYTES | 12582912 | Entire HTTP body, including multipart framing and form fields |
| MAX_UPLOAD_BYTES | 10485760 | Single uploaded file |
| MAX_ROWS | 20000 | Nonempty imported rows, collected records and stored reviews per product |
| MAX_FORM_FIELD_BYTES | 65536 | One multipart text field (at most eight fields and one file) |
| MAX_COLUMNS | 64 | Spreadsheet/CSV columns |
| MAX_REVIEW_CHARS | 5000 | Stored review text; existing upload/collection cleaning truncates and reports it |
| MAX_CSV_FIELD_CHARS | 20000 | Every CSV or XLSX field, including headers, before review cleaning |
| MAX_XLSX_ENTRIES | 256 | ZIP member count |
| MAX_XLSX_EXPANDED_BYTES | 41943040 | Actual total decompressed ZIP bytes |
| MAX_XLSX_ENTRY_BYTES | 20971520 | One decompressed ZIP member |
| MAX_XLSX_RATIO | 1000 | Maximum declared uncompressed/compressed member ratio |
| MAX_COLLECTION_BYTES | 2097152 | One upstream JSON response, streamed in bounded chunks |
| MAX_EXPENSIVE_REQUESTS | 1 | Concurrent mutating HTTP requests per application process |
| MAX_PRODUCTS_PER_OWNER | 100 | Physically stored products for one verified owner, including expired rows |
| MAX_ANALYSIS_RUNS | 20 | Stored analysis snapshots per product |

For a low-memory evaluation, consider smaller values such as MAX_ROWS=2000, MAX_COLUMNS=32,
MAX_UPLOAD_BYTES=2097152, MAX_REQUEST_BYTES=3145728 and MAX_ANALYSIS_RUNS=5. These are configuration examples,
not a measured production sizing recommendation. Keep request bytes above the file budget plus multipart
metadata, and the field budget at least as large as the intended review-text input. The unchanged frontend
still advertises its original 10 MiB client limit; the backend remains authoritative for stricter deployments.

## Accepted formats and content validation

CSV supports UTF-8/BOM or Windows-1252, with comma, semicolon, tab or pipe delimiters. Strict CSV quoting is
required; extra fields are rejected rather than silently treated as an inferred pandas index. Known ZIP,
legacy Excel and PDF signatures and binary control characters are rejected as CSV. CSV has no universal magic
signature: acceptance means structurally valid bounded text, not proof of origin or malware scanning. MIME
headers are untrusted and do not determine the parser. Duplicate headers are disambiguated; collisions after
normalization are rejected. Blank rows/empty unnamed columns retain their existing treatment.

XLSX must be a valid ZIP workbook containing its content-types and workbook XML. Every archive member is
streamed to enforce actual expansion totals/CRC validation before openpyxl opens it. Duplicate/path-traversal,
encrypted, binary/macro and external-link members are rejected; nothing is extracted to the filesystem.
XML DTD/entity declarations and NUL-encoded XML are rejected before XML parsing. Worksheet cell coordinates
are checked before openpyxl iteration, so understated dimensions and sparse far-away cells cannot force
unbounded empty-row/column expansion. Declared dimensions beyond the limits also fail closed. Only the first
worksheet is imported; archive budgets and worksheet coordinate checks apply throughout the workbook,
including relocated XML sheet parts. Worksheet relationships must target .xml parts.

Openpyxl uses read-only mode with external links disabled. Formulas in the imported sheet are rejected;
openpyxl does not evaluate formulas. CSV formula-like strings remain inert text during ingestion; existing
CSV report formula escaping remains in place. Legacy XLS, XLSM and other formats remain unsupported. Export
plain values as CSV when a workbook contains unsupported features. Workbooks and upload handles are explicitly
closed; the installed multipart parser also closes spooled files when parsing raises, including cancellation.
An upload-route parser wrapper requires a complete closing boundary and closes every parser-created file,
including unfinished file parts absent from FormData. It allows one file and eight form fields. The wrapper
uses Starlette's internal form cache and handle list; dependency upgrades must retain the lifecycle regression tests.

## Atomicity, ownership and retention

Product/review writes and analysis snapshots commit together. Parser, quota or analysis failures close the
request session and roll back pending rows; there is no partial import product. Manual review insertion also
checks the per-product row and text limits. Reanalysis enforces the row/run budgets before NLP execution.
Collection response bytes and incoming record counts are bounded; refreshing cannot accumulate unlimited
reviews or snapshots. Upstream compressed responses are rejected to avoid an uncontrolled decompression path.

Product quotas use the backend's verified principal, never a client-supplied owner ID. Existing owner/expiry
checks and PostgreSQL root locks still protect updates; new-product SQLite transactions reserve the writer
before quota reads, avoiding deferred read-to-write races. The global/per-owner HTTP admission gate is process-local; product
quota counts are not a distributed reservation mechanism. Multiple processes/instances require a separately
reviewed atomic quota/admission design. Existing SQLite concurrency tests synchronize request starts before
writer reservation, rather than requiring two writer reservations to coexist.

Original product creation/expiry fields are not updated by these limits. Seven-day access expiry and bounded
physical cleanup remain as described in [RETENTION_OPERATIONS.md](RETENTION_OPERATIONS.md). Persistent identity
accounts are untouched. Expired rows still consume storage quota until physically cleaned; operators must
activate and monitor retention before public use. Snapshot deletion or product deletion can reclaim quota.

## Errors, cleanup and remaining production risks

Expected invalid files return sanitized 400/415 errors; body/file/row/column/archive/storage budgets use 413,
with CSV tokenizer field overflows reported as a generic invalid-CSV 400. Busy requests return 429. No raw
parser errors, review text, credentials or SQL parameters are added to operational logs. Preview samples
remain private data intentionally returned only to the authenticated caller.

Request-scoped spool files are closed on success, validation failure and parser/read cancellation. A network
disconnect before the complete body is received never starts parsing. A disconnect after a complete request
may not cancel synchronous worker processing: it can finish and commit the whole import. This checkpoint does
not promise CPU preemption, crash-proof temp-file erasure or transactional delivery acknowledgments. Process
crashes require an isolated temp directory and host cleanup policy; backups/WAL/logs are outside request cleanup.

These are input/workload bounds, not a hard RSS/CPU budget or public deployment approval. Pandas tables,
openpyxl shared strings, NLP/model state and snapshots multiply memory usage. One admitted large request can
still be expensive. Slow uploads can occupy admission until proxy timeout, and GET analyses/reports and auth
verification remain outside this mutating-request gate. Public hosting still needs measured memory/latency
budgets, ingress timeouts, account/IP rate limits, signup abuse controls, TLS, restricted CORS, filesystem
isolation, monitoring and retention scheduling. Larger multiprocess deployments need shared enforcement.
Live disposable PostgreSQL verification is recorded below. Concurrent deployment quotas still need
verification against the eventual production topology before enabling public access.

## Local verification

On 2026-11-15, the complete backend suite passed **555 tests, with 18 skipped** (17 opt-in PostgreSQL
integration tests and one optional Ollama test). The upload-security module now has 33 cases: 31 local cases
and two opt-in live PostgreSQL cases. Local cases cover size/structure limits,
archive expansion, sparse dimensions, formula/entity rejection, malformed and cancelled multipart cleanup,
transaction rollback, owner-scoped quotas, admission release, upstream response bounds and valid input.
Existing upload, ownership, NLP, database concurrency and retention regressions also pass. Two old fixtures
were adjusted: one CSV now quotes comma-containing fields, and the concurrent creation barrier precedes the
new SQLite writer reservation. Their sentiment and uniqueness/isolation assertions remain intact.

Frontend tests passed **242**; lint, production/static-demo builds, both bundle checks and git diff --check
passed. All 10 static-demo output files remained byte-identical to the approved baseline, and both existing
SQLite application files retained their original hashes. No real review data, credentials, cloud resources,
deployment or commit was introduced. Live PostgreSQL results follow below; no application RSS/CPU benchmark is claimed.


## Final review additions

The final review added per-owner single-write admission even when the process-wide setting permits multiple
writes. This closes same-owner product-quota races within one application process; independent instances or
multiple application objects do not share admission state. Concurrent SQLite creation at the final quota slot
is regression-tested. PostgreSQL product quota counts remain non-atomic across processes; production must use
one process until shared/transactional quota reservation is reviewed.

Worksheet coordinate validation now scans every XML part instead of relying on the conventional worksheet
folder. A relocated-sheet regression reproduced the former bypass before the fix. Worksheet relationship
targets must end in .xml, and relationship XML receives the same NUL/DTD/entity checks as other XML.

Lifecycle tests pass with the installed FastAPI 0.162.7 and Starlette 1.10.0. Starlette is a transitive
dependency, not separately pinned here. Its internal form cache and parser handle list remain a compatibility
risk requiring these tests on dependency updates.

The two added PostgreSQL cases test owner-scoped upload-quota rollback and concurrent analysis-limit checks
under the existing root lock. They reuse the dedicated loopback/database-marker fixture. They **passed live on 2026-11-15**, together with the other PostgreSQL integration cases.
The focused PostgreSQL/retention/upload-security run passed all 55 cases (17 live PostgreSQL cases).
The full backend run with TEST_POSTGRESQL_URL enabled passed 572 cases with only the optional Ollama case
skipped; the separate default run passed 555 with 18 skipped. Frontend validation again passed 242 tests,
lint, both builds and both bundle checks.

Docker was already running. The disposable PostgreSQL 17.12 container used a verified 536870912-byte memory
limit, one CPU, loopback-only 127.0.0.1:55432, no host mounts and tmpfs database storage. Credentials were
randomly generated and stored only in mode-0600 temporary files. The runner removed inherited PG* variables
and DATABASE_URL before setting the dedicated test URL. The fixture enforces the exact loopback port/database,
restricts URL options and verifies the database comment marker before creating random test schemas.
The fixture itself does not reject inherited libpq environment overrides: future runners must likewise clear
PG* variables (especially PGHOSTADDR/PGSERVICE). This is a runner prerequisite, not a fixture guarantee.
No cloud/application database was used. All schemas were removed (zero remained), then the container and
credential files were removed. Container memory peaked at 168677376 bytes; this measures PostgreSQL only.

All ten static-demo output hashes and both existing application SQLite hashes matched the pre-validation
snapshot after the builds and tests. Exactly the original 14 intended files remain changed/untracked, with
nothing staged. No additional implementation or test changes were needed in this final pass. The checkpoint
is ready for Git review approval with the documented single-process and deployment limitations; no commit,
push, deployment, scheduler activation or GitHub Pages change was performed.

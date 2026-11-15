# Phase 2C.2 API rate limits and abuse protection

## Pre-implementation audit (2026-11-15)

The approved Phase 2C.1 base is `3559a240b7e3b46a5e503af4f2c8cebf2e9ebc13`.
The audit covers every router in `app/api` and the middleware stack.

| Endpoint family | Cost and existing controls | Gap before Phase 2C.2 |
|---|---|---|
| Authentication/session | No login/signup/refresh endpoints in this API. JWT verification runs before body parsing; local mode only accepts loopback. Browser sessions belong to the configured identity provider. | Repeated failed tokens can repeat verification; provider signup/session abuse is external. |
| Products, reviews, history, compare, stored analysis and stored AI reads | Authenticated owner and expiry filters; review/history pagination, stored product/review/analysis caps. Some responses materialize full stored snapshots. | No request-frequency budget. |
| CSV/XLSX preview/import | Body/file/field/row/column/ZIP budgets; multipart cleanup; worker thread; mutating admission. Import analyses atomically. | Repeated sequential uploads bypass concurrency limits. |
| App Store from-url/refresh | Fixed supported adapters, timeout/page/response-size/record bounds; mutating admission and analysis quotas. | No per-owner source-call frequency budget. |
| Reanalysis and review add/delete | Row/run limits, transaction rollback, PostgreSQL root locks, mutating admission. Review add/delete may automatically analyse. | No frequency budget; implicit analysis must be counted too. |
| AI generation/status | Generation is optional, local Ollama only, timeout and evidence validation; POST admission. GET status can contact Ollama. | Sequential generation and availability probes lack frequency limits. |
| PDF/CSV exports | Owner/expiry checks and bounded stored inputs. | GET generation bypasses mutating admission and has no frequency limit. |
| Health/sites and framework docs/OpenAPI | Health checks the database; sites is static. Health/sites bypass JWT; docs/OpenAPI are public. | No anonymous request limits; monitoring can compete with users. |

Existing admission is one mutating request per process by default and one per verified owner. SQLite
new-product creation reserves the writer before quota counts; PostgreSQL root locks serialize updates.
PostgreSQL new-product quotas remain non-atomic across independent processes. Seven-day owner access expiry
and physical retention behavior are already established and must remain unchanged.

## Implemented limits

All settings are read at process startup. Counts, window seconds and table capacities must be positive
integers or startup fails. `RATE_LIMIT_ENABLED` accepts only `true`, `false`, `1`, `0` (case-insensitive).
Defaults apply in both JWT and loopback local mode. Local mode shares one owner workspace; for deliberate
local load testing, raise the budgets or explicitly set `RATE_LIMIT_ENABLED=false`. Hosted use must keep it on.

| Environment variable | Default | Applies to |
|---|---:|---|
| RATE_LIMIT_ENABLED | true | Both frequency gates; disabling does not disable Phase 2C.1 admission or quotas |
| RATE_LIMIT_WINDOW_SECONDS | 60 | Window duration for all buckets |
| RATE_LIMIT_MAX_IDENTITIES | 4096 | Maximum active identities in each of the peer and owner tables |
| RATE_LIMIT_GLOBAL_REQUESTS | 3000 | All incoming HTTP attempts reaching the limiter, across peers |
| RATE_LIMIT_PEER_REQUESTS | 600 | All attempts per socket peer, including anonymous public and failed authentication requests |
| RATE_LIMIT_GENERAL_REQUESTS | 120 | All requests with a verified owner, including unknown routes and invalid input |
| RATE_LIMIT_INGESTION_REQUESTS | 10 | POST upload preview/import combined |
| RATE_LIMIT_ANALYSIS_REQUESTS | 10 | Upload import, from-url, refresh, explicit analyze, review POST and review DELETE combined |
| RATE_LIMIT_COLLECTION_REQUESTS | 5 | POST products/from-url and products/{id}/refresh combined |
| RATE_LIMIT_EXPORT_REQUESTS | 10 | GET report.pdf/report.csv combined |
| RATE_LIMIT_AI_REQUESTS | 5 | POST ai-summary and GET ai/status combined |

Product listing/detail, review/history reads, compare, stored analysis and stored AI overview reads consume
the general budget. Product create/patch/delete and history delete also consume the general budget and
retain write admission and database quotas. There are no API authentication/session mutation routes to limit;
all attempted API authentication is covered by the pre-verification peer/global gate. Public GET health/sites,
docs, redoc, OpenAPI and unknown non-API paths consume peer/global budgets without creating owner entries.
There is deliberately no health bypass: probes must account for this budget and 429/503 responses.
Treat a rate-limited health response as overload, not evidence to restart the process; restarting resets
limits. Keep probe frequency within the shared peer budget and review ingress liveness/readiness policies.
CORS handles browser preflight before the limiter; preflight does not run authentication or application work.
This cheap CORS-only response remains available after peer exhaustion. OPTIONS without preflight headers
still reaches the limiter; preflight does not bypass quotas on the eventual application request.
WebSockets and ASGI lifespan events are outside this HTTP limiter. There are no application WebSocket routes.

## Algorithm, responses and identity

Each identity has a fixed window starting on its first admitted request. All its operation counters expire
with that window. Window time uses `time.monotonic`, independent of wall-clock changes. This is a frequency
budget, not pacing: requests can burst up to the count immediately, and two budgets can be spent near a window
boundary. The concurrency gate still bounds expensive work. Configured limits apply to attempts, including
validation failures, 404s, downstream failures and admission rejections; successful responses do not refund
attempts. Owner counters are checked/incremented atomically as one operation: a refused category does not
consume another owner category. The independent outer global counter counts peer rejections, and the peer
counter counts owner rejections. Authentication failures never allocate owner entries.

The response is HTTP 429 with `{"detail":"Too many requests. Please retry shortly."}` and `Retry-After` as
positive integer seconds, rounded up until the rejecting window expires. Phase 2C.1 concurrency 429s retain
`Retry-After: 5`. These values are retry guidance, not a reservation: another request or another gate can
still reject the retry. Browser CORS exposes Retry-After alongside Content-Disposition. No owner IDs, IPs,
credentials, tokens, review contents, exception messages or remaining counts appear in limiter responses.
Internal limiter errors fail closed with a sanitized HTTP 503 and Retry-After: 5, before body reads or database
dependencies. Downstream exceptions continue through existing application error handling.

Private keys come exclusively from `request.state.principal` set by verified JWT authentication (issuer and
subject) or the reserved local principal. Keys are SHA-256 digests of that owner, not bearer tokens, product IDs,
query parameters or X-Owner-ID headers. Changing tokens, paths or products cannot create another owner budget.
Operation classification uses the decoded ASGI path and method, strips trailing slashes conservatively, and
ignores the query. Unknown/malformed paths still consume peer/global and, if authenticated, general budgets.
Future expensive routes must be added to the category function and its tests.

Peer keys use the ASGI client address, canonicalizing IPs and IPv4-mapped IPv6. Missing/non-IP peers share one
fallback bucket. The limiter does not parse Forwarded or X-Forwarded-For, and authenticated users behind a NAT
or reverse proxy still share the peer budget while retaining separate owner budgets. **Run Uvicorn with
`--no-proxy-headers` to preserve the socket peer** unless a separately reviewed, explicitly trusted proxy setup
is in place. Uvicorn can otherwise rewrite the ASGI client before middleware sees it; this application cannot
recover the original socket address. Never use wildcard forwarded-header trust. A proxy deployment can raise
the shared peer limit after measurement, retaining owner/global limits and enforcing IP limits at the ingress.
The identity provider needs its own login/signup/password-reset protections; this API does not control them.

## Memory, concurrency, database and retention guarantees

Two identity dictionaries hold at most RATE_LIMIT_MAX_IDENTITIES entries each, with fixed-length digest keys
and a fixed set of counters. One additional global bucket is constant space. Expired entries are reclaimed
lazily on request traffic: no scheduler or background task is introduced. Cleanup scans at most the configured
capacity; this is bounded work, not a claim of constant request latency or a measured memory budget. When a
table is full, a new identity gets 429 until the earliest slot expires. Active entries are never evicted,
preventing identity churn from resetting quotas. This trades availability for bounded storage: an attacker
can occupy slots. Failed/rejected attempts do not extend a slot's expiry. Log messages use fixed vocabulary.

A lock serializes each table's check-and-increment across threads/event loops within the process. The
existing event-loop admission gate remains: all mutations, plus PDF/CSV GET exports and AI status probes,
share MAX_EXPENSIVE_REQUESTS (default 1), with at most one admitted expensive request per verified owner.
Admission releases on completion/failure/cancellation. Frequency rejection precedes multipart parsing,
body buffering, database dependencies, external collection, NLP and report generation, so it cannot create
partial rows. Worker processing already started before a later disconnect may finish and commit atomically,
as documented in UPLOAD_SECURITY.md; rate limiting does not preempt it.

No schema, SQL, ownership predicate, creation deadline, seven-day expiry or cleanup behavior changes here.
SQLite writer reservation and PostgreSQL root locking/rollback behavior remain as implemented. Existing
product/review/history storage quotas stay in force. No shared quota reservation or new persistent identity
store is introduced. SQLite remains the local backend; limiter decisions do not access either database.

## Single-instance operations and remaining risks

Run **one application instance with one worker/event loop**. Each app object/process has independent limits
and admission; restarts reset windows. Multiple workers multiply budgets and concurrent work, while
PostgreSQL new-product quota counts are not atomic across processes. Database locks serialize existing-root
updates, but do not make HTTP quotas distributed. Before adding workers/instances, review shared atomic
rate/admission and product quota reservation. No Redis, queue, paid service or cloud provisioning is added.

Monitor 429/503 counts at the ingress with bounded route/category labels, request latency, active work,
process RSS/CPU, database lock/pool failures and source/Ollama availability. The limiter emits fixed
`API rate limit rejected request (peer|owner)` informational messages and a generic error on internal failure.
Aggregate rather than retaining raw identifiers, tokens or query strings; sample/rate-limit log collection
at the ingress to avoid log-volume abuse. This phase adds no metrics server or scheduler. Check normal
browser workflows and probe frequency before tuning, and watch capacity rejection when many identities
arrive inside a window. A denied request can still consume network bandwidth and JWT work if it reaches the
owner gate; the peer/global gate bounds counts, not verification concurrency or connection memory.

These controls do not replace ingress body/connection/header limits, TLS, slow-client timeouts, signup abuse
controls, network isolation, retention operations or measured memory/latency budgets. Shared proxy/NAT peer
budgets and global limits can deny other users under abuse. Large authenticated read responses still consume
memory and are frequency-limited rather than serialized by expensive admission. The in-memory limiter is
best-effort process-local protection, not a public deployment approval. The static Pages demo is unchanged.

## Phase 2C.2 verification (2026-11-15)

The final default backend suite passed **598 tests, 19 skipped**. The 44 new rate-limit cases (43 local, one opt-in PostgreSQL)
cover within/exceeded budgets, rounded Retry-After, expiry/recovery with a fake clock, owner isolation,
anonymous/failed-auth handling before JWT verification, atomic concurrent checks, bounded identity capacity,
forwarded-header/token/query/path bypass attempts, sanitized fail-closed behavior at both gates, category
coverage including implicit analysis, rejection before body/database access, no partial imported/review rows,
shared collection/AI/export budgets, cancelled admission cleanup, CORS exposure and invalid configuration.
Existing authentication, cross-account isolation, valid uploads/collection, SQLite transaction/concurrency,
rollback and retention regressions also passed. The shared client fixture now creates one fresh app per test
so process-local limiter state does not leak across unrelated test lifetimes; error injection targets that app.

The default run's 19 skips are 18 opt-in PostgreSQL integration cases and one optional live Ollama test.
After explicit approval, the focused PostgreSQL/retention/upload-security/rate-limit run passed **99 tests**,
including all 18 live PostgreSQL cases and all 44 rate-limit cases. The full backend suite with PostgreSQL
integration enabled passed **616 tests, one skipped** (optional live Ollama). The full suite retains its
isolated SQLite tests as well as running the opt-in PostgreSQL cases; it does not move every test to PostgreSQL.
These are live Phase 2C.2 results, not reused Phase 2C.1 results. No SQL or migrations changed; eventual
production topology and proxy configuration still require separate verification.

Frontend tests passed **242**. Lint, production and static-demo builds, both bundle checks and git diff --check
passed. All ten static-demo output files retained their exact hashes/file set, and both existing application
SQLite files retained their hashes against the approved checkpoint. The nine changed/untracked files are
backend source, tests and this document only. No secrets, generated artifacts or application data are included;
nothing is staged and no commit/push, deployment, Pages change, scheduler, service or queue was introduced.


## Final security review additions

The nine-file review found no implementation change necessary. Five additional regression cases cover
multiple verified owners sharing an exhausted peer (including health/preflight policy), staggered identity
expiry at capacity, collection and AI service failures releasing admission without refunding request budgets,
and rate rejection against PostgreSQL preserving product/review/analysis rows, owner isolation and the exact
seven-day deadline. The PostgreSQL case uses the existing exact loopback/database/marker fixture; it is not
an unguarded connection. Request rate rejection still precedes admission and body/database work.

The reviewed live runner clears inherited PG* and database URL variables, verifies container memory/CPU/port
and mount settings, and writes generated credentials with mode 0600 from creation. The fixture alone does not
reject inherited PGHOSTADDR/PGSERVICE overrides; environment sanitation remains a runner prerequisite.
Untrusted forwarding headers are ignored by application code; a deployment must also preserve the socket
peer at Uvicorn or explicitly review trusted proxies. No actual hosting/proxy configuration is validated here.


## Approved live PostgreSQL verification and cleanup

Before startup, preflight verified 8 GiB host RAM (53% reported free), 62 GiB available disk, an already-running
Docker engine with about 3.8 GiB VM RAM, a locally available PostgreSQL 17 Alpine image and successful bind
availability on 127.0.0.1:55432. Docker Desktop was not started or reconfigured. The dedicated database URL and
marker guards were reviewed before test schema creation.

Exactly one temporary PostgreSQL 17.12 container ran with verified 536870912-byte memory and swap ceilings,
one CPU, loopback-only port 55432, no host mounts and disposable tmpfs storage. Test-only credentials were
randomly generated into files created with mode 0600, and inherited libpq PG* overrides were cleared in the
test subprocess environment. No cloud, provider or application database was used.

Passing cases confirm owner isolation, unchanged seven-day deadlines, rollback after rejected uploads and
failed transactions, concurrent root locking/quotas, rate rejection before partial writes, and admission
release after service failures/cancellation. The new PostgreSQL rate-limit case leaves exactly two products,
12 reviews and two analysis snapshots after rejecting repeat upload/review requests, and checks cross-owner
404 and unchanged original retention timestamps.

Cleanup found zero remaining test schemas. Only the owned temporary container and its generated credential
files were removed; tmpfs storage was discarded. Docker container and volume inventories matched
the preflight baseline afterward. Network names were preserved, but the default bridge ID changed during
the run (5dd653090db6 to 8848f34903f5); no network create/remove/prune or Docker restart commands were issued.
The cause of that engine-managed bridge identity change was not established. Port 55432 was released. The implementation and test files remained
byte-identical throughout this approved run; only this document was updated to record results. All ten demo
files and both application SQLite hashes still match the approved checkpoint. Exactly nine intended files
remain changed/untracked; nothing is staged. No commit, push, deployment, scheduler or Pages action occurred.
The checkpoint is ready for Git approval with the single-worker/proxy/capacity/resource-sizing limitations
above; it is not approval for public deployment.

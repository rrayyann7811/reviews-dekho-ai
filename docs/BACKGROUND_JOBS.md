# Phase 2C.3 durable background processing

## Architecture audit and scope

Base: `5e52ef67b7fb87eef8bc28796970e5ac038b06d0`. The existing processing_jobs table
is a product-linked retention foundation (id, product_id, created_at, status, result), not an active queue.
Products own reviews, immutable analysis snapshots and jobs through ON DELETE CASCADE. Authentication derives
owner identity from verified JWT context or the local workspace; job visibility must join the existing
product owner/expiry predicate. Account products expire at the earlier stored deadline or seven days from
creation. Local products retain their existing exemption. Refresh/reanalysis must never extend deadlines.

Uploads parse bounded CSV/XLSX, create reviews, analyse and commit atomically. Collection performs external
I/O outside the write transaction, then reauthorizes the product and commits reviews plus analysis. Their
existing response shapes/statuses promise completed analysis. Preview is a bounded synchronous read. AI
generation performs its own commits and network calls. None is moved into this queue in this phase: durable
upload payload storage, external side-effect idempotence, AI publication and changed response contracts need
separate design. Only analysis of already stored reviews is supported as an opt-in new API. Existing POST
analyze, uploads, collection, review edits and exports remain synchronous and retain their contracts.

SQLite uses explicit transactions and needs IMMEDIATE writer reservation before queue decisions. PostgreSQL
locks product roots before child jobs, matching existing write/retention ordering. Existing HTTP limits are
process-local and apply only to requests; a separate worker needs database-enforced execution bounds and
must recheck stored review/history quotas. Existing application databases will not be migrated by this task.

## Implementation plan

1. Append SQLite v8 and PostgreSQL revision 0002; preserve prior migration history and existing rows/results.
2. Add product-scoped, idempotent analysis-job creation, status/list and queued cancellation. Bound global,
   owner and product queue storage, and count job creation against the existing analysis/general rate limits.
3. Add explicit polling CLI, default concurrency one, with fenced durable claims, atomic result publication,
   bounded retries and recovery. No automatic startup, scheduler, Redis, Celery or in-memory work queue.
4. Test lifecycle, isolation, concurrency, migrations, rollback, retention and API controls before full
   backend/frontend/build validation. Live PostgreSQL requires separate approval.

## API and lifecycle

- `POST /api/products/{id}/jobs` with `{"requestKey":"client_request_001"}` returns 202 and a durable
  analysis job. requestKey is required (8–64 ASCII letters/digits/underscore/hyphen), scoped to the product.
  No arbitrary task kind, owner, URL, upload bytes, file path or model instructions are accepted. Unknown
  fields fail validation. A repeated key returns the same job even after it finishes, fails or is cancelled;
  use a new key for a deliberate new analysis. Retry after a lost acknowledgment with the same key.
- `GET /api/jobs/{id}` returns status, attempt counts, timestamps, sanitized error and an optional analysisId
  and resultUrl. `GET /api/products/{id}/jobs?limit=20&before_id=...` pages up to 50 jobs, newest first.
  Claim tokens, request keys and arbitrary stored legacy JSON are never returned.
- `POST /api/jobs/{id}/cancel` cancels a queued job, including one waiting for a retry. Repeating queued
  cancellation is idempotent. Running/succeeded/failed jobs return 409. Running cancellation is intentionally
  unsupported: synchronous NLP cannot safely be preempted. A request can wait on a root lock, or time out
  with the existing generic database 503, if execution has already started. Retry status after contention.
- After success, follow resultUrl to the existing `/api/history/{analysisId}` owner-scoped snapshot. Existing
  product analysis/report endpoints can use that run. This is a reference, not a second stored review copy.
  Deleting the analysis through the existing history API clears the job result reference with ON DELETE
  SET NULL, preventing a reused SQLite analysis ID from redirecting it to another run. Previously obtained
  URLs can still return 404 or follow normal resource ID semantics; a succeeded job is not automatically rerun. Parent deletion cascades the job itself.

Normal lifecycle: queued → running → succeeded / failed. Queued → cancelled is user cancellation. Transient
or unexpected execution failures can return running → queued with a bounded delay; exhausted or deterministic
validation/quota failures become failed. Retention expiry encountered during execution becomes cancelled.
Legacy pending/queued/running foundation rows are disarmed as cancelled during migration, preserving their
existing result JSON. Rows without a request key are never claimed. This avoids treating old placeholder
records as executable work.

Job creation consumes the existing general and analysis request-rate budgets. Status/list consume general;
cancellation consumes general and existing write admission. HTTP 429/Retry-After and 503 fail-closed behavior
remain as in API_RATE_LIMITS.md. Idempotent submission attempts still count as HTTP attempts. Queue storage
caps return 413; a different request key while a product already has queued/running work returns 409. At most
one active job per product is accepted. Completed/failed/cancelled jobs and expired-but-not-cleaned rows still
consume physical storage quota. Product deletion and the existing explicit retention operator can reclaim
space. No automatic cleanup or scheduler is activated here.

Creation validates stored reviews/history counts. Execution rechecks MAX_ROWS and MAX_ANALYSIS_RUNS through
the existing analysis service. A synchronous operation can consume a history slot while a job waits; the job
then fails cleanly, without a partial snapshot. Queuing does not reserve a history slot against synchronous
APIs, and no quota is bypassed. Job analysis uses the reviews/name/domain/category stored **when execution
obtains the product lock**, not a frozen copy taken at enqueue time. The resulting analysis is immutable.

## Transactions, claiming and duplicate handling

Claims commit separately and include a random internal fencing token, lease deadline and incremented attempt.
Only one eligible row is selected per poll, ordered by job ID; there is no prefetch list. Expired running jobs
are eligible for recovery. PostgreSQL locks the product root with SKIP LOCKED, then the job, rechecking
eligibility after locking. SQLite starts an IMMEDIATE transaction before reading queue state. Both serialize
claims; all code that needs both locks takes the product root first, matching product deletion/retention.

Execution uses a fresh transaction and verifies running status plus the exact token under product/job locks.
Analysis snapshot insertion and the succeeded job/result reference commit together. Unexpected exceptions,
interruption, commit failure or process loss roll back the snapshot transaction; the durable claim remains
recoverable. A separate transaction records retry/failure after an ordinary exception. No raw exception text,
SQL parameters, credentials or review content is stored in errors or worker log messages.

A recovered claim gets a new token; stale attempts cannot publish. A running execution holds its root/job
locks for the whole computation, so another worker cannot recover it merely because its lease has elapsed.
PostgreSQL claimers skip that locked root; SQLite permits only one writer. Reexecuting an already succeeded
token is a no-op. This guarantees atomic publication of at most one snapshot per job, not exactly-once CPU
execution: work interrupted before commit can be computed again. If commit acknowledgment is lost, a later
failure recorder cannot overwrite an already succeeded job because its token/status no longer matches.

Account owner/deadline is always derived from the product, never from a job request. It is checked at claim,
execution start and again before publication using the earlier stored/seven-day deadline. Job creation never
extends parent retention. Expired jobs become invisible through the existing owner/expiry predicate; physical
cleanup cascades all job states and results under the parent. The worker does not physically purge data.
Local data retains its existing no-expiry behavior. A claimed job whose parent is deleted is a safe no-op.

SQLite holds the writer reservation through NLP: API writes and other workers may wait or return database
503 under contention. PostgreSQL holds row locks and a database connection through NLP, so same-product
mutation/cancellation/retention may wait or skip; unrelated roots remain available. This deliberate tradeoff
avoids large input copies and distributed fencing side effects. Measure latency before hosting; large NLP
jobs must fit operator transaction/session limits. Lease duration is recovery guidance, not a CPU timeout. Retry/lease/retention timestamps use UTC wall time;
synchronize the host clock, since clock corrections can alter recovery timing.

## Explicit worker startup, shutdown and migration

No worker starts with Uvicorn or application import. No scheduler or service registration is installed. After
review, a separately authorized operator must stop writers, back up the intended database, and explicitly
apply SQLite migrations with an explicit SQLite DATABASE_URL and `.venv/bin/python scripts/migrate_sqlite.py` or PostgreSQL `alembic -c alembic.ini upgrade head`.
SQLite v8 and PostgreSQL 0002 are append-only. Existing application files are not upgraded by this task;
startup refuses old schemas. SQLite migration backups use the existing runner. Destructive downgrade is
refused. Test databases are isolated and disposable.

From backend/, with an explicitly set DATABASE_URL and the same engine/NLP settings as the API
(the worker refuses an unset URL or a missing SQLite file):

```
.venv/bin/python -m app.job_worker
```

The CLI performs read-only schema/cascade preflight before polling. SIGINT/SIGTERM stops new polls, waits
for current transactions to finish and then releases threads/connections. There is no hard CPU preemption.
A supervisor must allow enough shutdown time; forced termination rolls back in-flight database writes and
leaves a claim to recover after its lease. Database unavailability emits a fixed generic message and waits
for the next bounded poll. Startup/shutdown failures exit nonzero without a private exception traceback.
No automatic supervisor restart or scheduler is configured here.

| Setting | Default | Meaning |
|---|---:|---|
| JOB_CONCURRENCY | 1 | Worker threads, 1–4. SQLite always uses one; PostgreSQL uses advisory slots |
| JOB_POLL_SECONDS | 5 | Positive interruptible delay after each worker iteration, including success/error |
| JOB_LEASE_SECONDS | 300 | Positive lease before interrupted/abandoned claim recovery |
| JOB_RETRY_SECONDS | 30 | Positive retry base; delay is base × current attempt (bounded by max attempts) |
| JOB_MAX_ATTEMPTS | 3 | 1–5, persisted at creation, includes claims interrupted by crashes |
| JOB_MAX_STORED | 500 | Global physically stored job rows |
| JOB_MAX_PER_OWNER | 50 | Physically stored jobs joined to one verified product owner |
| JOB_MAX_PER_PRODUCT | 20 | Physically stored jobs for one product, including terminal states |

All settings are read at startup; invalid/nonpositive values fail. PostgreSQL queue creation uses a
transaction advisory lock around global/owner storage counts, plus the product root lock; SQLite uses its
writer reservation. Worker threads each hold at most one connection and one job. Configure the worker pool
for at least JOB_CONCURRENCY connections (queue mode fails startup otherwise). Queue backlog is database
state, not an unbounded in-memory executor queue. Each loop always waits, so even an empty queue or outage
cannot spin without a configured delay.

PostgreSQL worker slots use **session advisory locks**, held on the same dedicated connection across claim,
execution and failure recording, then explicitly unlocked before returning the connection. An uncertain
unlock invalidates the connection. Use a direct PostgreSQL connection or a verified session-pooling proxy;
**transaction-pooling proxies are unsupported for this worker**. API connection pooling remains unchanged.
One namespace is shared across worker invocations targeting the same database, so accidentally starting a
second worker with matching configuration cannot claim a slot already held by the first. All invocations
must use the same JOB_CONCURRENCY value; this is not a multi-tenant distributed worker scheduler.

## Deployment limits and remaining risks

Use one API process and one explicitly managed worker process, default concurrency one. HTTP admission and
rate limits remain local to the API, while background execution is bounded by SQLite's writer or PostgreSQL
worker slots. They are **separate budgets**: a synchronous API operation and a background job on another root
can run at the same time. There is no claim of one shared CPU/RSS cap across both processes. Keep default
worker concurrency one and measure combined model/process memory before deployment. Multiple worker
processes duplicate model memory even when advisory slots prevent concurrent execution. No such persistent
worker is activated by this implementation or local verification.

Database claims, queue caps and fencing protect supported paths using the same database. They do not make
HTTP rate limits or new-product quotas distributed. Independent databases and differently configured worker
slot ranges do not share guarantees. More workers/instances, transaction-pooling proxies, asynchronous
uploads/collection/AI and cancellable CPU work require separate review. A running job can be long, and older
jobs can delay newer ones; there is no fairness/priority scheduler, dead-letter service or progress estimate.

Monitor queued/running counts, oldest available/lease age, attempts/failures, database lock/pool errors,
worker liveness, RSS/CPU and shutdown duration using bounded labels and sanitized logs. Configure ingress
limits, trusted proxy behavior, TLS, retention operations and operator alerting separately. No hosting,
cloud provisioning, paid service, deployment, scheduler or Pages change is performed in this phase.

## Local verification (2026-11-16)

The complete default backend suite passed **636 tests, 28 skipped**. New job coverage has **38 passing local
cases and nine opt-in PostgreSQL cases**. The 28 total skips are 27 live PostgreSQL cases (18 existing plus
nine new) and one optional live Ollama case. After separate approval, Phase 2C.3 live PostgreSQL verification
passed as recorded below. These are results for this schema/worker diff, not reused Phase 2C.2 evidence.

Deterministic cases use controllable UTC clocks and transaction/thread barriers instead of sleep-based
assertions. They cover creation and idempotent keys, owner isolation and expired access, queued cancellation,
concurrent claims and duplicate execution, bounded retries/exhaustion, rollback after a snapshot has flushed,
process interruption and fencing, graceful stop after current work, concurrent final-slot storage quota,
retention cascade and deadline checks during execution, synchronous-analysis quota interaction, rate-limit
integration and invalid requests/settings. A deletion/reused-ID case verifies the result FK clears safely.
Read-only schema preflight refuses partial/missing SQLite targets. Mocked PostgreSQL connection failure tests
verify uncertain advisory acquisition/rollback/unlock state invalidates a connection, including BaseException;
these mocks are not evidence of live PostgreSQL locking behavior.

The new guarded PostgreSQL module reuses the exact loopback/database/marker fixture and includes migration
preservation, concurrent claim/execution, slot exclusion with an expired-but-locked lease, retry rollback,
interruption/fencing, retention and concurrent global queue quotas. The existing offline Alembic compilation
and schema-chain tests pass; the frozen baseline remains untouched. The schema comparison now applies the
baseline and revision 0002, and the authentication/recovery-token route inventory now checks all 28 private
operations, including the four new endpoints. No old isolation assertions were removed.

Frontend tests passed **242**. Lint, production/static-demo builds, both bundle checks and git diff --check
passed. All ten static-demo output files retain their byte hashes and exact file set, and both existing
application SQLite files retain their approved hashes. No migration was applied to those files. Fourteen
intended source, migration, test and documentation files remain changed/untracked; no credentials/generated
artifacts are included, nothing is staged, and HEAD remains the approved base. No commit, push, deployment,
scheduler, persistent worker or GitHub Pages change occurred. Live PostgreSQL verification is recorded
below; operational application migration and worker activation still require separate approval.


## Approved live PostgreSQL verification (2026-11-16)

Preflight confirmed Docker was already running (29.9.3), 8 GiB host RAM with 40% reported free, about 3.8 GiB
Docker VM RAM, 62 GiB available disk, the locally available PostgreSQL 17 Alpine image and successful bind
availability on 127.0.0.1:55432. The exact loopback/database URL and marker guards were reviewed before schema
writes; inherited PG* environment overrides and database URLs were removed before setting the dedicated
test URL. The unrelated container, volume and network inventory was recorded before startup.

Exactly one approved temporary PostgreSQL 17.12 container ran with 536870912-byte memory/total-memory-plus-swap
limits, one CPU, loopback-only 127.0.0.1:55432, no host mounts and disposable tmpfs storage. Random test-only
credentials and state were created with mode 0600 and never printed. Docker itself was not started or
reconfigured. No cloud/provider/application database was used.

Results:

- All nine new live PostgreSQL job cases: **9 passed**.
- Focused migration, concurrency, worker recovery, retention, upload-security and rate-limit suite:
  **183 passed**.
- Full backend suite with PostgreSQL integration enabled: **663 passed, one skipped** (optional live Ollama).
  This runs the 27 opt-in PostgreSQL cases alongside the existing isolated SQLite tests; it does not change
  every test to PostgreSQL.

Passing cases cover fenced lease recovery, no publication by stale/duplicate attempts, concurrent claiming,
advisory worker-slot exclusion even after a lease expires, interruption/connection release and recovery,
bounded retries with atomic rollback, root locking, owner isolation, retention deadlines/cascades and atomic
global job quotas. The new migration preserves legacy result JSON and disarms old placeholder jobs. Mocked
uncertain-lock failure tests also passed in the focused/full suite; they complement rather than replace the
live slot/interruption tests.

Cleanup found **zero remaining test schemas**, stopped/removed only the owned temporary container, discarded
its tmpfs storage and deleted its generated credential/state files. Port 55432 was bindable afterward.
Container and volume inventories matched preflight. Network names were preserved, but the default bridge ID
changed from **8848f34903f5** to **d21832bce5ea** during the run. The cause was not established; no network
create/remove/prune, network repair or Docker restart command was issued. Docker network identity is not
claimed unchanged.

All implementation, migration and test files remained byte-identical during this verification; only this
document was updated with results. The 14-file scope is preserved, nothing is staged, HEAD remains the
approved base, and all ten demo files plus both application SQLite hashes remain unchanged. No application
worker/scheduler was activated and no application migration, commit, push, deployment or Pages action was
performed. The checkpoint is ready for review with the operational limits above; this is not public hosting
or worker-activation approval.

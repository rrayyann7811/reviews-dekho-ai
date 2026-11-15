# Phase 2B.1: PostgreSQL compatibility and migration foundation

This is local preparation, not a database cutover or deployment. SQLite remains the default. No application
database has been migrated, copied or deleted; tests use temporary databases. No Supabase project, scheduler,
worker, cloud resource or paid service is created. The GitHub Pages synthetic demo is unchanged.

## Compatibility assessment

The existing ORM uses portable integer keys, JSON, dates, strings, foreign keys and indexes. Product ownership
scopes every child review, analysis and AI record. Owner-scoped source uniqueness and per-product review IDs
work on both dialects; NULL source fields intentionally allow multiple uploaded/manual products.

The old runner is SQLite-specific: `PRAGMA user_version`, positional `?` SQL, `DATETIME`, SQLite column changes
and file backups cannot be used on PostgreSQL. SQLite needs explicit foreign-key enforcement and explicit
transaction BEGIN for atomic DDL. SQLite also returns naive timestamps, whereas PostgreSQL TIMESTAMPTZ returns
aware values. SQLite does not enforce VARCHAR lengths as PostgreSQL does; legacy imports need length/type
validation. JSON remains JSON here; no JSONB-specific operators or indexes are required by existing queries.

Previously startup applied legacy migrations, including an old drop-column migration. Now existing schemas
are checked and require an explicit stopped-app upgrade. A brand-new SQLite file can still initialize at
startup. PostgreSQL startup performs read-only revision/table/column checks and never creates or upgrades a
schema. Unknown, old or incomplete schemas fail closed; connection failure never falls back to SQLite.

## Schema histories and data preservation

SQLite retains the append-only `app/migrations.py` history. New migration **7** only adds `processing_jobs`
and its product foreign-key index. Existing products keep their owners, deadlines and snapshots. The runner
uses SQLite's backup API (including committed WAL pages) before upgrades, with private backup permissions.
Each legacy step and its version update are transactional. Failed steps roll back; earlier completed steps
remain committed. Restore the pre-upgrade snapshot to undo the entire sequence. No migration was edited or
reordered; changes to backup/startup behavior are separate from the historical migration functions.

PostgreSQL has an independent frozen Alembic baseline, **0001_postgres**, for an empty application schema:

- `products`, including owner/expiry indexes and unique `(owner_id, source_site, external_product_id, source_region)`.
- `reviews` with unique `(product_id, external_id)` and cascading product FK.
- `analysis_results` with immutable JSON snapshots and cascading product FK.
- `ai_summaries` with cascading analysis FK.
- `processing_jobs` with a cascading product FK and in-row JSON result.

All timestamps are TIMESTAMPTZ on PostgreSQL. The ORM normalizes datetime inputs/results to UTC; legacy naive
SQLite values are interpreted as UTC. Existing stored SQLite timestamp values are not rewritten.
The frozen Alembic baseline does not import live ORM metadata. Tests compare its columns/nullability/FKs
with the models and compile its PostgreSQL SQL. Future model changes require both a new SQLite step and a
new Alembic revision; never edit an applied revision or use `stamp head` to hide a mismatch.

Online Alembic runs serialize operators with a transaction-scoped PostgreSQL advisory lock. DDL and revision
updates run in one transaction; failures roll back together. The baseline deliberately refuses destructive
downgrade. Transactional migration failure/recovery was verified on disposable local PostgreSQL 17.12.
An existing nonempty schema without matching history is not automatically adopted, overwritten or inferred.

## Configuration

Backend settings are environment variables read at process startup; `.env` is not automatically loaded.
Never commit connection strings with credentials. Keep credentials in an approved secret manager/environment
or a protected operator service file. No connection credentials are included in the repository.

| Variable | Default / purpose |
|---|---|
| `DATABASE_URL` | Existing `backend/storage/reviews_dekho.db` SQLite file. PostgreSQL uses `postgresql+psycopg://…`; `postgresql://` and `postgres://` normalize to Psycopg 3. |
| `DB_POOL_MODE` | `queue`; `null` disables application pooling when an approved external pool is used. |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `2` / `0` per application process. |
| `DB_POOL_TIMEOUT` | `5` seconds waiting for an application pool connection. |
| `DB_CONNECT_TIMEOUT` | `5` seconds for PostgreSQL connection setup. |
| `DB_STATEMENT_TIMEOUT_MS` | `30000`; limits PostgreSQL statements, not sentiment-processing wall time. |
| `DB_LOCK_TIMEOUT_MS` | `5000`; bounds row/advisory lock waits. |

Psycopg **3.3.9** and Alembic **1.20.1** are pinned. The engine uses pool pre-ping, hidden SQL parameters,
UTC sessions and disabled automatic prepared statements. Queue connections recycle after 300 seconds.
Non-loopback TCP hosts require `sslmode=verify-full`; supply the provider CA with `sslrootcert` where needed.
Supported URL query options are SSL options, `application_name` and `channel_binding`; host/service/options
overrides are rejected. Use DB_* variables for limits. Remote TLS has not been exercised against a provider.

Direct/session PostgreSQL connections are the initial target. NullPool/disabled prepared statements are a
pooler foundation, not proof of compatibility with Supabase/PgBouncer transaction mode. Some poolers reject
startup `options`; test that behavior, connection budgets and timeouts before selecting a service. Never
disable TLS verification to work around provider configuration. No hosting region, plan or cost is approved.

## Explicit commands

From `backend/`, after installing the project's requirements:

```bash
# Stop the application first. Review the intended SQLite path and keep an independent backup.
DATABASE_URL=sqlite:///./storage/reviews_dekho.db .venv/bin/python scripts/migrate_sqlite.py
```

For PostgreSQL, review SQL **without connecting**:

```bash
DATABASE_URL=postgresql+psycopg://localhost/reviews_dekho_test \
  .venv/bin/alembic -c alembic.ini upgrade head --sql
```

Only after separate approval for a dedicated target database, stop the application and set its reviewed
`DATABASE_URL` securely. Select a non-exposed application schema/search_path with appropriate grants before
running the following online commands. These were verified against the disposable local test database only;
the last `current` reported `0001_postgres (head)`:

```bash
.venv/bin/alembic -c alembic.ini current
.venv/bin/alembic -c alembic.ini upgrade head
.venv/bin/alembic -c alembic.ini current
```

Review future Alembic revisions before running them. Autogeneration is not configured as a substitute for
reviewed dual-dialect migrations. No tables under a managed provider's identity/auth schema are created or
altered. SQLAlchemy owner filters do not protect a separate Supabase Data API: use a non-exposed schema and
restricted grants, or independently tested RLS, before any managed database connection.

## Transactions, concurrency and health

PostgreSQL mutation requests select the owned, unexpired product with `FOR UPDATE OF products`. History
deletion locks the same parent. Read-only views remain unlocked. Network collection and optional model I/O
release their read transaction, then recheck ownership/expiry and reacquire the parent before storing data.
Repeated collection races still rely on the database unique index and return a conflict; ownership checks
are never replaced by a caller ID or an in-memory cache.

Each request has its own session; closing a failed request rolls back uncommitted changes. Connection/lock
operational failures return generic 503 responses; integrity conflicts return generic 409 responses without
SQL parameters. The existing `/api/health` executes `SELECT 1`; pool pre-ping detects stale connections at
checkout. Neither health checks nor recovery silently create a replacement database.

Authorization is checked at the database statement/request boundary. A request that began before expiry may
finish after it; no promise of interrupting in-flight processing is made. Product deadlines are not updated
by refresh, reanalysis or GET requests. Future workers must reauthorize before every result write.

## Retention relationships

Authenticated product creation records one UTC instant for `created_at` and exactly seven days later for
`expires_at`. Local workspace products remain non-expiring. An expiry equal to now is invisible; purge selects
deadlines less than or equal to now. Jobs, original reviews, all historical analyses and AI attempts inherit
the original product deadline. A job created/retried on day six does not receive a new seven-day lifetime.
`job_query` provides the same owner/expiry scope for future job access; there is no public job API or worker.
Unattached/pre-import jobs are not supported and need a separately reviewed owner/deadline model later.

`scripts/purge_expired_data.py` deletes products in a transaction, cascading to reviews, runs, AI attempts,
jobs and their stored JSON results. It does not query/delete identity-provider users; this database has no
account table. Expiring records never expires the user's account. No scheduler is introduced in Phase 2B.1.

PDF/CSV exports are generated in memory; there are no persisted export files to delete. Upload request temp
files are request-scoped, not durable job artifacts. Model files and synthetic fixtures are not user review
artifacts. Future stored exports/uploads/object storage need an owner-linked artifact registry and deletion
retries before use. Backups, SQLite free pages/WAL and provider/log retention remain separate erasure work;
physical row deletion alone is not a claim of full seven-day retention compliance.

## Cutover, rollback and remaining requirements

There is **no automatic SQLite-to-PostgreSQL data transfer**. Keep local real review data local. Prefer a new
empty hosted application database. An approved transfer would need an offline export/import tool, counts and
snapshot digests, explicit UTC conversion, VARCHAR length/JSON/date validation, preserved owners/original
creation/deadlines and PostgreSQL sequence reset after explicit ID import. That tool is not implemented.

Before any production migration, stop writes, take a consistent private backup and prove restoration in a
separate database. For PostgreSQL use an approved `pg_dump`/`pg_restore` workflow with service-file/secret
configuration; do not put passwords in command arguments or logs. Review provider backup retention/costs.
On migration failure, keep the app stopped; investigate the transaction state and retry only after validation.
For rollback, restore the verified backup to a separate target and point the matching application version to
it. Do not force a destructive baseline downgrade, drop application tables or falsify version markers.
SQLite rollback similarly restores a quiescent backup file with its matching schema/application version.

Before public deployment: repeat the integration suite on the target PostgreSQL version/service;
test provider-specific pooler/TLS behavior and failure recovery; validate schema/grants,
password-AMR authentication, cross-user APIs, timeout/resource budgets and backup restore. Rate/body/ZIP/
processing limits, quotas, scheduled purge and backup/log retention remain Phase 2B.2/later blockers.

## Validation scope

The initial offline checkpoint recorded 492 backend passes and five skips. The subsequent approved live-local
verification used an official `postgres:17-alpine` image running **PostgreSQL 17.12**, Linux arm64/musl. Native
PostgreSQL tools were absent, but Docker Desktop was already running. No daemon, cloud service or application
database was created or replaced beyond the explicitly approved disposable test container.

| Run | Actual result |
|---|---|
| Original four previously skipped PostgreSQL tests | **4 passed** against real PostgreSQL. |
| Expanded integration module | **17 passed**: ten live PostgreSQL tests and seven no-connection safety-guard cases. |
| Full backend suite with `TEST_POSTGRESQL_URL` set | **509 passed, 1 skipped** (live Ollama unavailable). Existing SQLite tests and the ten live PostgreSQL tests both execute. |
| Full default backend suite without that variable | **499 passed, 11 skipped** (ten PostgreSQL tests plus live Ollama). SQLite regression coverage executes normally. |
| Frontend suite | **242 passed**. |

Frontend lint, production/demo builds and both bundle checks passed. All ten demo output files remain
byte-identical to the previously approved baseline. Credential scans, documentation link/format checks and
`git diff --check` passed. The repository path contains spaces; the actual Alembic CLI commands work there.

Live PostgreSQL coverage now verifies empty-schema migration/idempotence, startup revision checks, foreign
keys/cascading deletion, owner-scoped uniqueness, concurrent updates with real blocking row locks, lock timeout
and transaction recovery, UTC/TIMESTAMPTZ under a non-UTC session timezone, exact expiration boundaries,
product-linked job retention, pool exhaustion/reuse, a terminated test connection and reconnection, and migration
DDL/version rollback followed by recovery. JWT-authenticated API coverage includes uploads, products, reviews,
reanalysis/history, comparisons, PDF/CSV exports, foreign-owner denials, recovery-token rejection and deletion.
No application compatibility defects were found; this verification extended tests/guards and documentation.

The test fixture now accepts only an explicit `postgresql+psycopg` URL for **127.0.0.1:55432**, database
**reviews_dekho_test_2b1**, with no host/service overrides. Before schema writes it also requires this database
comment: `Reviews Dekho disposable PostgreSQL integration test database`. The marker was set inside the known
temporary container. Test schemas have unique `rd_test_` names and are removed by fixture cleanup. Set the
marker only in a database known to be disposable; never label an application/production database for testing.
The tests do not accept the formerly broader `reviews_dekho_test*` naming rule. Unconfigured runs skip live
tests rather than falling back to mocks. Test credentials are supplied privately through the environment,
not source files, command arguments, fixtures or documentation.

## Approved local test resources and cleanup

The single container was limited to **512 MiB RAM, 1 CPU and 128 PIDs**, published only on
`127.0.0.1:55432`. PostgreSQL data used a **256 MiB tmpfs**; no project files, user directories, host bind mounts
or persistent volumes were mounted. The image digest was
`sha256:d3244e8ce3f165ee3c93d9c4a4b1d0fe48b3a89e2287b717fdcbbde92d405065`.

Before starting, the Mac reported 8 GiB physical memory, 50% system-wide memory free and approximately 62 GiB
available disk space. Docker had no running containers. Recorded PostgreSQL container usage peaked at
**93.02 MiB charged memory**, used approximately **63.2 MiB tmpfs storage**, and consumed about **2.76 CPU-seconds**
over its measured lifetime; the OOM-killed flag remained false. These are local test observations, not production
capacity/latency benchmarks. Host memory-free percentage was still 50% at the final resource check.

After validation, only the task's uniquely named, labeled container was stopped/removed. Its tmpfs data and
writable layer were discarded, generated test credential files were deleted, and port 55432 was free. No
containers or volumes remained, matching the initial state. The downloaded image remains cached (approximately
396 MiB); unrelated images/build caches and the already-running Docker daemon were left untouched. Existing
SQLite files were hash-checked before/after and remained unchanged. All original 24 checkpoint files remain.

Production/provider TLS, session/transaction poolers, least-privilege roles/RLS, other PostgreSQL versions,
backup restoration and production workload/resource limits remain unverified. Local tests used a disposable
administrative test role for schema creation/connection-failure injection; they do not establish a production
grant policy. Scheduled retention and backup/log/object-storage deletion remain separate work.

## Repeating validation

With an explicitly approved equivalent local environment and protected `TEST_POSTGRESQL_URL` supplied:

```bash
# From backend/; integration fixture validates the exact target and marker before schema writes.
.venv/bin/python -m pytest tests/test_postgres_integration.py -v
.venv/bin/python -m pytest
```

Separate offline tests generate PostgreSQL DDL, mock engine/startup failures, compile scoped row locks, compare frozen
revision structure to ORM metadata, execute its portable operations on temporary SQLite, and exercise actual
SQLite migrations, WAL backups, rollback, concurrent uniqueness, UTC and retention boundaries. Executing
portable revision operations on SQLite does not establish PostgreSQL integration success.

```bash
# From backend/; local PostgreSQL integration skips unless separately configured.
.venv/bin/python -m pytest
# From frontend/
npm test
npm run lint
npm run build
npm run check:app-bundle
npm run build:demo
npm run check:demo-bundle
```

Reference design checked against [Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[offline SQL generation](https://alembic.sqlalchemy.org/en/latest/offline.html) and
[SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html).

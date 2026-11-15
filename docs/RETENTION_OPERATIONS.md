# Phase 2B.2: seven-day retention operations

This checkpoint implements a scheduler-compatible cleanup command. No timer, cron entry, cloud scheduler,
paid resource, deployment or public cleanup endpoint is activated. SQLite remains the local default and
existing application databases are not used by development tests. Persistent user identities remain with
the identity provider; retention never calls its account-management APIs.

## Policy and current data inventory

Private product data has a maximum seven-day lifetime from the original UTC `products.created_at` instant.
Normal creation stores `expires_at = created_at + 7 days`. Refresh, reanalysis, metadata edits and requests
do not extend either field. A stored earlier expiry is honored. An altered later or missing expiry cannot
extend the original creation-time cap: both API visibility and physical cleanup apply that cap. Private
product records with missing expiry remain hidden while awaiting their original deadline. Local workspace products
(`owner_id=local`) remain non-expiring and are explicitly excluded even if an incorrect expiry is present.

At an expiry equal to the cleanup cutoff, the product is eligible. Each run captures one UTC cutoff; products
expiring after that instant wait for the next run. Synchronize the host clock. There is no CLI override that
allows a future cutoff. The internal clock injection exists only for deterministic tests.

| Data | Expiry/deletion relationship |
|---|---|
| Products | Eligible private roots are physically deleted. |
| Original reviews | Product FK cascade deletes text, titles, reviewer names and input metadata. |
| Analyses/history | Every product-linked historical snapshot is deleted by cascade. Reanalysis creates no new retention lifetime. |
| Optional AI attempts | Analysis FK cascade deletes accepted/rejected attempts and their evidence/output. |
| Processing jobs/results | Product FK cascade deletes all job statuses and in-row JSON results, including jobs created later. No live worker exists yet. |
| Persistent identities | No identity table is referenced or deleted; accounts survive removal of their review data. |
| PDF/CSV downloads | Generated in memory; no durable export files exist in the current application. Previously downloaded copies cannot be retracted. |
| Request upload temp files | Request-scoped multipart storage, outside this DB purge; not durable job artifacts. Process/crash temp-file policies require deployment review. |
| Backups, WAL/free pages, logs | Outside row cleanup; separate expiration/erasure policies are required. |

The earlier helper performed an unbounded delete and the old CLI printed one count. The new helper removes
one bounded batch (also used opportunistically by collection); the standalone command manages multiple short
transactions and reports acknowledged progress. It does not delete database files, run migrations, vacuum,
remove backups or walk arbitrary filesystem paths.

## Safe commands

Run from `backend/` with the backend dependencies installed. **DATABASE_URL must be explicitly supplied**
through an approved protected environment/service file, even for the default SQLite file. Missing targets,
SQLite memory URLs, SQLite URL query overrides, missing files and unsupported configurations fail closed.
Never put real database passwords in shell arguments, logs, source code or cron command lines.

For a reviewed existing SQLite file:

```bash
DATABASE_URL=sqlite:///./storage/reviews_dekho.db \
  .venv/bin/python scripts/purge_expired_data.py --dry-run --batch-size 100 --max-batches 10

DATABASE_URL=sqlite:///./storage/reviews_dekho.db \
  .venv/bin/python scripts/purge_expired_data.py --batch-size 100 --max-batches 10
```

For PostgreSQL, load the reviewed `DATABASE_URL` securely, then use the same command/flags. Do not point it
at a live service merely to test setup. Connection/TLS/pool limits still follow
[POSTGRESQL_MIGRATION.md](POSTGRESQL_MIGRATION.md). No SQLite/PostgreSQL schema is created or upgraded by the
command; expected schema versions, tables and deletion cascades must already exist. Incorrect schema exits
without deletion and must be migrated separately during a stopped-app maintenance window.

Options:

- `--batch-size`: 1–1000 products per transaction, default 100.
- `--max-batches`: 1–1000 batches per invocation, default 10. Runs do not loop forever on a backlog.
- `--dry-run`: read-only estimates for the same bounded scan. It never performs trial deletes/rollbacks as
  its estimate mechanism. PostgreSQL uses repeatable-read/read-only transactions; SQLite enforces query-only
  connections and discards them afterward so that setting cannot leak into the API pool.
- `--owner-id`: optional trusted operator scope, a 64-character lowercase verified-owner hash. This is not
  a frontend/user authorization mechanism. The local owner and malformed IDs are rejected. Reports omit it.

Batch limits count **root products**, not total cascade rows, bytes or processing time. One heavily populated
product may have many reviews/snapshots. Use smaller batches and existing DB statement/lock timeouts if
necessary; public per-account/run quotas remain separate work.

## Structured output and exit codes

Normal execution emits one JSON object on stdout. It contains a random operational `run_id`, status, dry-run
flag, fixed cutoff, duration, completed nonempty batches, acknowledged committed batches, per-table matched
and deleted counts, a remaining-work boolean and a sanitized error category. No review text, names, URLs,
product IDs, account IDs, credentials or raw SQL/driver exception messages are emitted. `--help` prints help.
Argument/configuration errors also emit JSON, with zero deletion counts; their shorter report may omit run
metadata because a run never began.

For example, a successful single-product apply may report these counts:

```json
{
  "products": 1,
  "reviews": 6,
  "analyses": 2,
  "ai_summaries": 1,
  "jobs": 1
}
```

This is an illustrative `deleted` object, not a complete report or measured production workload. Dry-run's
`deleted` values are always zero; `matched` describes the estimated eligible rows. Under concurrent traffic,
dry-run batches are individual snapshots, not one global database snapshot. Estimates can change before an
apply. `remaining=true` means more work exists within the run's cutoff/scope, including locked PostgreSQL roots.

| Exit | Meaning | Operator action |
|---|---|---|
| 0 | Bounded scan complete at its cutoff. | Record success and retain only sanitized operational metrics. |
| 2 | Invalid arguments/configuration or schema/cascade mismatch. | Fix the configuration/schema; do not blindly retry or auto-migrate. |
| 3 | Partial progress/backlog, including locked eligible products. | Schedule another bounded invocation; investigate persistent backlog/locks. |
| 4 | Database/transaction or connection-disposal failure. | Check connectivity, permissions, storage, timeouts and resource health; retry transient faults with bounded backoff. |
| 130 / 143 | SIGINT / SIGTERM interruption handled. | Retry; current uncommitted batch rolls back, earlier batches remain committed. |

## Transactions, concurrency and recovery

PostgreSQL selects eligible roots with `FOR UPDATE SKIP LOCKED`, counts only their children, then rechecks
eligibility in the delete. Root locks serialize with API product mutations and FK-linked child insertion.
Another cleaner can process different roots without double-counting them. A locked root is left for a later
run and causes a partial result if it remains eligible. Read-only previews do not take those write locks.

SQLite uses `BEGIN IMMEDIATE` for each apply batch. This obtains the single writer reservation before counts
are read, preventing an unsafe deferred read-to-write upgrade. Readers may retain an older snapshot; writes
wait up to SQLite's busy timeout or fail safely. WAL readers can continue while cleanup commits. Non-WAL
readers can delay commit. Database/query-only cleanup does not convert journal modes or force a vacuum.

Each batch's product delete and database FK cascades commit atomically. Counts become reportable after commit;
failed/interrupted batches contribute no acknowledged deletion counts. Cleanup is idempotent: a rerun only
finds records still present and eligible. Results use plain delete row counts rather than an outstanding
`RETURNING` fetch, avoiding a cursor lock retained by an interrupted SQLite fetch. Result sets are explicitly
closed, and sanitized failure handling clears unwound exception-frame references so an interrupted candidate
SELECT cannot retain a cursor lock through the reported exception. Tests retain that exception while retrying.
Connection-disposal failures also produce sanitized JSON (`resource_cleanup_failure`, exit 4); previously
acknowledged commits are preserved in the report.

SIGTERM/SIGINT request graceful rollback/reporting; a running DB statement may take until its timeout before
Python handles a signal. SIGKILL, host failure or a lost commit acknowledgment can prevent a final report or
make its counts incomplete. A crash between commit and reporting can underreport actual progress. Summaries
are operational observations, not a transactional audit ledger. Database state is authoritative; retry safely
instead of trying to recreate deleted private content. Keep retry limits/backoff outside the command rather
than hiding an unlimited retry loop inside it.

Future workers must tolerate deleted parents and must reauthorize ownership/expiry before writing. Cleanup
deletes product-linked job rows even if marked running; there is currently no worker to cancel and no durable
artifact store. A future worker/artifact system must add cancellation/deletion retries before public use.

## Scheduling recommendation: single instance

Recommend an external process on the **same host/database namespace**, initially every five minutes, with
one concurrent invocation. A Linux systemd timer/oneshot service or host cron can invoke the bounded command
without a paid scheduler product. This is a software-level recommendation, not a claim that a hosting plan
offers it for free. Approve provider capabilities/costs separately; no service has been provisioned here.

Example unit fragments for a later reviewed Linux host (documentation only):

```ini
# reviews-retention.service
[Service]
Type=oneshot
User=reviews-retention
WorkingDirectory=/srv/reviews-dekho/backend
EnvironmentFile=/etc/reviews-dekho/retention.env
ExecStart=/srv/reviews-dekho/backend/.venv/bin/python scripts/purge_expired_data.py --batch-size 100 --max-batches 10
TimeoutStartSec=300
TimeoutStopSec=45

# reviews-retention.timer
[Timer]
OnBootSec=1min
OnUnitInactiveSec=5min
```

Use a restrictive owner/group and permissions for the environment file. A systemd timer does not start a
second copy of an already active service. Cron needs an equivalent reviewed non-overlap wrapper. macOS
development can use an approved launchd/manual invocation instead; nothing is installed into launchd here.
For a sleeping/free-tier host, timer delays/suspension are a real limitation, not a guaranteed deletion SLA.

SQLite cleanup must see the actual persistent SQLite file; a remote CI runner's ephemeral disk is not that
database. PostgreSQL could use an approved remote scheduled job with TLS and protected credentials after
network/role/plan review. No public cleanup webhook or HTTP admin endpoint is added. Do not put a privileged
database/service-role key in frontend variables or schedule cleanup from the synthetic GitHub Pages demo.

Access expiry occurs at the deadline. **Physical deletion occurs on the next successful cleanup**, with at
least the scheduling interval, processing time, outages and backlog affecting delay. Five-minute scheduling
is a proposed operational target, not a hard seven-day erasure guarantee. Approve a physical-deletion grace
window and alerting policy before claiming retention compliance. If zero grace is mandatory, this periodic
job alone is insufficient; a separately reviewed deadline-aware operational design is required.

## Monitoring, roles and operator verification

Monitor last successful run age, exit/status, duration, committed batches, deletion counts and persistent
`remaining=true`. Alert on missing runs, repeated partial/failed runs and duration approaching the scheduler
timeout. Verify a known synthetic expired cohort disappears across all five application tables while active
and local cohorts remain. Confirm that identities can still sign in/create a new product afterward.

The scheduler is a trusted database operator. Give it only reviewed application/catalog read privileges,
product-delete privileges and the privileges required for PostgreSQL row locking; verify RLS/grants do not
silently hide the cleanup backlog. It does not need identity-provider administration privileges. Test actual
production roles separately; SQLAlchemy owner filters do not protect a separately exposed Data API.

Before activation, an operator must verify the target/role/schema, run a dry-run, inspect its content-free
summary, apply a small batch against synthetic data, confirm child counts/cascades, test retry/interruption,
and validate monitoring. Do not use real review data for development verification. Existing SQLite files are
not copied/deleted by this task, and no new schema migration is needed for this cleanup implementation.

## Outside database cleanup and remaining deployment work

Row deletion does not securely erase SQLite free pages, WAL/journals, filesystem/VM snapshots, PostgreSQL WAL,
replicas or provider backups. Backup/log retention and restoration procedures must not resurrect expired data
into a publicly accessible app; rerun cleanup and verify access policy before serving a restored database.
Retention after backup restore, backup TTL, logging/analytics policies, crash temp-file cleanup and future
object-storage/export deletion require separate operator controls. This command never deletes arbitrary files.

Do not enable SQL echo/debug logging containing private parameters. The CLI's own output is content-free,
but platform/database access logs are outside its control. Restrict and expire those logs independently.
Public API abuse protection, upload/ZIP/body/processing quotas, hosting persistence/resource checks,
authentication/pooler/TLS/grant validation and the approved physical-deletion SLA remain prerequisites.

## Verification

Tests use temporary SQLite databases and synthetic text. They cover exact boundaries, original-creation caps,
missing/extended expiry, owner/local preservation, cascade counts, persistent identity sentinels, bounded
progress, repeated execution, database-enforced dry-run, concurrent cleaners/WAL readers, interrupted deletion,
actual CLI SIGTERM handling, sanitized connection/schema failures and CLI argument safety.
Live verification on 2026-11-15 used an explicitly approved, disposable official PostgreSQL 17 Alpine
container running **PostgreSQL 17.12**. All **15 live integration tests** passed, including five new retention
tests for skip-locked roots, concurrent cleaners, cascades/owner scope, read-only dry runs and interrupted
deletion. Seven additional target-guard cases passed (**22 tests** across the two integration modules).
The existing integration cases also exercised migration/rollback, API ownership, UTC expiration boundaries,
job retention inheritance, row locking and connection/pool failures. These are actual database tests;
SQL compilation or mocks are not substituted for live execution.

The full backend suite with PostgreSQL integration enabled passed **539 tests, with one optional Ollama
test skipped**. Most backend tests still use isolated SQLite fixtures; enabling integration does not make
every backend test a PostgreSQL test. The separate default SQLite run passed **524 tests, with 16 skipped**
(15 opt-in PostgreSQL tests and the optional Ollama test). The focused SQLite retention/CLI suite has
**25 tests**. Frontend tests passed **242**; lint, production/demo builds and both bundle checks passed.
All 10 rebuilt static-demo files matched the baseline byte for byte, and both existing application SQLite
files retained their baseline hashes. No PostgreSQL compatibility defect required a source change in this run.

The dedicated database was `reviews_dekho_test_2b1`, protected by the loopback/port/name/query-parameter
guards and database marker; each fixture used its own disposable schema. The container was limited to
512 MiB RAM, one CPU and `127.0.0.1:55432`, with 256 MiB tmpfs database storage and no host-directory
mounts. Cgroup peak memory was **153,829,376 bytes (146.7 MiB)**; maximum observed database disk usage was
**49,004 KiB (47.9 MiB)**, sampled during tests and at cleanup, plus **20,480 bytes** in the container's
writable layer. Storage figures are observations, not a kernel-recorded high-water mark or production sizing.
All test schemas were gone before container removal. The task's container, tmpfs storage and generated
credential files were removed, and port 55432 was free afterward; unrelated Docker resources were untouched.

This verifies the local retention foundation, not production roles/RLS, hosting durability, scheduling,
backup erasure or deletion-latency guarantees. Those remain the deployment prerequisites described above.

References:
[PostgreSQL row locking/SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html),
[SQLite transaction behavior](https://www.sqlite.org/lang_transaction.html),
[systemd timer behavior](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).

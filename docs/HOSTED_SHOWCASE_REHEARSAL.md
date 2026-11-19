# Protected ONNX showcase rehearsal

This runbook is for a separately approved, invite-only rehearsal with synthetic uploads. Use two Vercel Hobby projects with roots `frontend` and `backend`, and one fresh Supabase Free project. Use Mumbai `bom1` and `ap-south-1` when the account offers both. If either is unavailable, choose the same nearby region for both, such as Singapore. Retain the existing GitHub Pages demo as a separate static build.

## Confirm free-tier eligibility before creating resources

- Vercel Hobby is for personal, non-commercial use. Python and FastAPI are available, and Fluid compute supports a 300-second Hobby maximum and the 4.5 MB request/response limit. The backend explicitly requests **35 seconds** and relies on the standard **1 vCPU / 2 GB** class. Confirm the assigned class and runtime in the account.
- The Phase 3E.1 staged tree was approximately **573 MB**, above the standard **500 MB** Python limit. The **5 GB Large Functions public beta** is available on eligible Fluid compute projects. New projects are enrolled automatically according to the announcement. Existing eligible projects opt in with `VERCEL_SUPPORT_LARGE_FUNCTIONS=1`. It excludes Static IPs and Secure Compute. Check eligibility, actual function bundle bytes, and the deployed function label. The measured tree is a Linux rehearsal bundle and the current Vercel dependency install can produce a different size.
- The build command downloads the pinned revision, verifies each SHA-256, and bundles those assets with the Function. The runtime reads and independently verifies them on initial inference. A network restriction, unavailable wheel, missing file, or checksum mismatch is a rehearsal failure. Runtime model fetching is disabled by design.
- Supabase Free currently lists 500 MB database space, 5 GB uncached egress, 50,000 monthly active users, and two active free projects. Nano documents 60 database connections, 200 pooler clients and default pool size 15. Projects may pause after a week of inactivity. The app stores review data. Upload files are transient, and reports are generated on request.
- Budget **$0/month** for a non-commercial rehearsal within the free allowances, with default domains and manual account creation. Vercel Hobby includes 4 active CPU hours, 360 GB-hours of memory, and one million Function invocations. Use a single WAF rule within its Hobby allowance and verify the dashboard billing terms before enabling it. Free quotas can stop service. A custom SMTP provider or domain can cost separately. Vercel Pro and Supabase Pro are separate paid upgrades and require new approval.

References: [Vercel Hobby](https://vercel.com/docs/plans/hobby), [Python runtime](https://vercel.com/docs/functions/runtimes/python), [Large Functions](https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size), [Function limits](https://vercel.com/docs/functions/limitations), [Vercel regions](https://vercel.com/docs/regions), [Supabase pricing](https://supabase.com/pricing), [Supabase compute limits](https://supabase.com/docs/guides/platform/compute-and-disk), [Supabase regions](https://supabase.com/docs/guides/platform/regions).

## Supabase setup and explicit migration

1. Create a fresh Free project. Disable self-service signup and anonymous sign-in. Use asymmetric signing keys. Set the Auth Site URL to the exact frontend HTTPS origin and allow its `/auth/confirm` and `/auth/recovery` redirects only. Verify signed issuer, audience `authenticated`, and password AMR in test sessions.
2. For the first two invited testers use operator-created, confirmed password accounts, through the Auth dashboard or the server-side Admin `createUser` operation. Send unique credentials through the approved private channel. Operator credential reset can be used if email is unavailable. Supabase's built-in SMTP only sends to project-team addresses and is limited to two messages per hour. Email invitations or self-service reset for external recipients require a separately approved SMTP setup. Keep admin credentials out of both deployments and browser bundles.
3. Disable the Supabase Data API for this project before exposing any app tables. Revoke default grants to `anon` and `authenticated` on app tables and sequences, or verify that those roles cannot access the data through any exposed route. The browser uses Auth only. Restrict the application runtime SQL login to the app schema and reviewed tables. It needs `SELECT` on `alembic_version` and the app tables for schema checking, plus `SELECT, INSERT, UPDATE, DELETE` on `products`, `reviews`, `analysis_results`, and `import_receipts`, and `USAGE` on their sequences. Use a separate migration owner with DDL privileges. Keep table/schema ownership, elevated roles, and role creation away from the runtime login. Test schema reflection with the deployed role.
4. Use a verified TLS **direct connection** for migrations and logical backups. If the operator network is IPv4-only, use the Supabase **session pooler** on 5432. Obtain the CA from the dashboard and use `sslmode=verify-full` with `sslrootcert` and the provider's actual DNS hostname. Load the migration `DATABASE_URL` from a private operator environment. Confirm the project ref and that the application schema is empty before running:

   ```sh
   cd backend
   .venv/bin/alembic -c alembic.ini upgrade head
   .venv/bin/alembic -c alembic.ini current
   ```

   Expect `0003_import_receipts (head)`. The FastAPI startup gate only checks schema; it does not migrate PostgreSQL. Keep Free-plan backups manual and encrypted, with a tested restore and a short retention period. For the synthetic pilot you can choose to keep no user-data backups. Restore drills must remove expired data before allowing access.
5. Set the Function's `DATABASE_URL` to the **shared transaction pooler** on 6543 with the project's actual pooler hostname and runtime login. Require `sslmode=verify-full` and point `sslrootcert` at a verified trust store available in the Function. If a separate public CA file is needed, verify it against the provider's download and include it in the backend bundle during the approved rehearsal. Use `DB_POOL_MODE=null`. The hosted engine disables prepared statements and sets UTC and query/lock limits inside each transaction, avoiding connection-startup flags that a transaction pooler may reject. Confirm the effective settings, role privileges, and shared advisory lock through the real pooler before opening access.

References: [Supabase SMTP](https://supabase.com/docs/guides/auth/auth-smtp), [Auth Admin createUser](https://supabase.com/docs/reference/javascript/auth-admin-createuser), [Connecting to Postgres](https://supabase.com/docs/guides/database/connecting-to-postgres), [Free backups](https://supabase.com/kb/faqs/platform/free-plan-backups).

## Vercel setup and release gates

Use the repository configurations in each project root. Use a stable HTTPS frontend URL and a stable HTTPS API URL for the rehearsal. Supabase JWT authentication protects all hosted API operations, including health, even if the API hostname is reachable. If enabling Vercel Authentication, first verify that approved testers can reach the frontend and that browser requests and CORS preflights still reach the API. Do not put a Vercel protection-bypass secret in the client. Vercel's newer announcement describes free production protection; verify the setting and access model in the actual account.

| Project | Configuration |
| --- | --- |
| Frontend | `VITE_AUTH_MODE=hosted`, `VITE_PUBLIC_DEMO=true`, `VITE_API_URL=https://<stable-api-host>/api`, `VITE_SUPABASE_URL=https://<project-ref>.supabase.co`, and its `VITE_SUPABASE_PUBLISHABLE_KEY`. Use the production Vite build and the configured SPA fallback for auth callbacks and deep links. |
| Backend | `PUBLIC_DEMO=true`, `REQUIRE_TRANSFORMER=true`, `SENTIMENT_ENGINE=transformer`, `AUTH_MODE=jwt`, `AUTH_AUDIENCE=authenticated`, actual `AUTH_ALGORITHM`, exact `AUTH_ISSUER` and `AUTH_JWKS_URL`, `CORS_ORIGINS=https://<stable-frontend-host>`, and the backend-only `DATABASE_URL`. Use the verified limits in `backend/.env.example`, including parser limits. Keep Ollama disabled and rate limiting enabled. Leave `MODEL_DIR` unset at runtime so the Function uses the bundled path. |

Configure the backend project's Hobby WAF IP fixed-window rule on `/api/*`, starting at **60 requests per minute per IP** with 429. Verify matching, CORS preflight, trusted client IP grouping, shared-IP behavior, and usage before inviting users. PostgreSQL admits at most one analysis or export transaction across all instances on the same database. Per-process limits still cover other application work. The WAF rule is IP-based and is not a global request budget. Require invite-only enrollment, watch CPU and database connections, and confirm quota exhaustion and a disable-access procedure. Use conservative owner quotas, for example `MAX_PRODUCTS_PER_OWNER=5` and `MAX_ANALYSIS_RUNS=3`. External collection, AI summary operations and background job routes are blocked server-side. The application has no workers or schedulers in Vercel.

Record actual Function artifact size, region, CPU and memory class, and strict model startup. With two accounts, verify password sign-in, CSV/XLSX at 10 rows and 1,000 characters, cold ≤30 s and warm ≤15 s, stored analyses and reports, cross-owner denial, replay after a lost response, and 429 across instances. Check actual hosted memory telemetry against the 1.25 GiB target where available. If it is unavailable, record that constraint and retain the native Linux memory evidence separately. The 1.25 MiB multipart cap and the observed report sizes fit within Vercel's documented 4.5 MB payload limit, but actual hosted timing and packaging remain unverified.

References: [FastAPI builds](https://vercel.com/docs/frameworks/backend/fastapi), [Vercel production protection](https://vercel.com/changelog/protect-production-deployments-for-free-on-every-plan), [Vercel WAF fixed windows](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting).

## Seven-day cleanup

For the protected rehearsal, the existing bounded cleanup CLI can be run by an approved operator or a separately approved private scheduler using a dedicated DB role and secret store. Start with a dry run against the confirmed rehearsal project:

```sh
cd backend
.venv/bin/python scripts/purge_expired_data.py --dry-run --batch-size 100 --max-batches 10
.venv/bin/python scripts/purge_expired_data.py --batch-size 100 --max-batches 10
```

The scheduler role needs schema reflection and read access, and permission to delete expired products and receipts. Cascades remove product-linked reviews, analyses, summaries, and jobs. The receipt foreign key retains early-delete tombstones until their own expiry. Schedule a single monitored invocation every 15 minutes if the private scheduler supports it. Supabase Cron is another option after approval and testing an equivalent bounded SQL job that excludes local-owned products, honors both product expiry and the seven-day creation cap, and removes receipts only after their own expiry. Vercel Hobby Cron runs at most daily per job and would require an authenticated maintenance endpoint, so this configuration adds none.

Verify with synthetic rows: an expired product and its child rows are physically removed, a live row for another owner remains, an early-delete receipt survives until expiry and blocks replay, and the receipt is then removed. Compare dry-run and committed counts and alert on backlog or failures. Recheck cleanup after a project resumes from pause. Review independent log and backup retention before making deletion promises.

References: [Supabase Cron](https://supabase.com/docs/guides/cron), [Vercel Cron limits](https://vercel.com/docs/cron-jobs/usage-and-pricing), [Project retention playbook](RETENTION_OPERATIONS.md).

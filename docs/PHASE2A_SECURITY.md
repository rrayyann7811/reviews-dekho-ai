# Phase 2A: authentication and ownership preparation

This is a local security checkpoint, **not approval or readiness for public deployment**.
No identity-provider project, PostgreSQL connection, hosting service or paid resource is created.
Existing GitHub Pages workflows and the static synthetic-data demo remain unchanged.

## Baseline and scope

Baseline: `main`, `0a8471d532b8e4d6a8b7156c2207135a9bfc174b`, clean working tree and matching remote main.
No AGENTS.md was present in the repository or checked ancestor directories. Baseline tests:
405 backend passed / 1 live-Ollama skip; 144 frontend passed.

Scope: verify access tokens before parsing private API bodies, enforce product ownership through all
child resources, preserve local mode, and enforce a seven-day account-data access window.
Persistent accounts belong to the managed identity provider; the application does not create, expire,
store passwords for, or delete those accounts. There is no jobs table or worker in this checkpoint.
Future jobs must carry an owner derived from the verified principal and authorize every status/result/cancel action.

## Authentication architecture

`AUTH_MODE=local` is the default for the existing local application. Requests to private `/api/` routes
are restricted to loopback peers (and the in-process TestClient peer). They use one reserved `local`
workspace. This mode must never be reverse-proxied or used for public hosting: a loopback reverse proxy
is not an authentication boundary. Never configure proxy trust to accept arbitrary forwarded client IPs.

`AUTH_MODE=jwt` requires explicit trusted issuer, audience, asymmetric algorithm and public keys.
Misconfiguration fails at app creation, without silently falling back to local mode.
The ASGI authentication middleware runs before multipart parsing and before a DB session is opened.
CORS wraps it, allowing legitimate preflight requests and exposing authentication failures to the configured frontend.

Verification uses PyJWT with cryptography. The operator selects exactly one of ES256, RS256 or EdDSA;
HS256, unsigned tokens and token-selected algorithms are not accepted. Require `iss`, `aud`, `sub`, `exp`,
`iat`; validate optional `nbf`, numeric timestamps, expiry and signature. The signed role must be
`authenticated`; anon/service-role and explicitly anonymous-user tokens are rejected. Ignore any user/owner
ID supplied through headers, query strings, JSON, upload fields or identity metadata.

Phase 2A.4 additionally restricts JWT-mode private data APIs to signed password authentication evidence:
the top-level `amr` array must contain `password`, contain no `recovery` or `anonymous` method, and have valid
numeric method timestamps no later than `iat`. Missing/malformed AMR fails closed. Confirmation, magic-link,
OAuth-only and recovery-only sessions cannot access application data. Fresh password sign-in is required
after confirmation or password recovery. See [the hardening review](AUTH_SECURITY_REVIEW.md) for the trusted
provider assumptions, limitations and BFF alternative. Local loopback mode is unchanged.

Public keys come from exactly one operator-configured JSON JWKS file or HTTPS JWKS URL. A file must contain
public asymmetric keys with unique IDs, not private/shared secrets. A URL is never derived from token claims
or headers. Reject embedded `jwk`, `jku`, `x5u` and unsupported critical headers. Remote JWKS uses the library's
five-minute cache, three-second network timeout and 30-second refresh cooldown; TLS verification stays enabled.
Local public-key files require an application restart to rotate. Verification failure or unavailable keys
rejects the request with 401 and a Bearer challenge; no token or provider error details are returned.

Offline JWT verification does not detect provider logout/account revocation instantly: a previously issued
access token can remain valid until expiry. Configure short access-token lifetimes later. Immediate revocation
would need additional provider/session validation; no claim of instant revocation is made here.

## API coverage

All 24 private operations below require authentication in JWT mode. Unknown/foreign/expired data returns 404;
scoped lists do not reveal foreign or expired records. Validation failures never substitute for ownership checks.

| Area | Operations |
|---|---|
| Products | GET/POST `/api/products`; GET/PATCH/DELETE `/api/products/{id}` |
| Collection | POST `/api/products/from-url`; POST `/api/products/{id}/refresh` |
| Analysis | GET `/api/products/{id}/analysis`; POST `/api/products/{id}/analyze` |
| Reviews | GET/POST `/api/products/{id}/reviews`; GET/DELETE `/api/products/{id}/reviews/{reviewId}` |
| History | GET `/api/history`; GET/DELETE `/api/history/{analysisId}` |
| Comparison | GET `/api/compare`, checking both products and any requested runs |
| Reports | GET `/api/products/{id}/report.pdf` and `.csv`, including explicit historical runs |
| Optional AI | GET `/api/ai/status`; GET/POST `/api/products/{id}/ai-summary` |

GET `/api/health` and `/api/sites` are public operational/source metadata. OpenAPI/Swagger remain public
route documentation, not user-data access. No other private `/api/` operation bypasses the middleware.
The tests enumerate OpenAPI operations so a new operation must be reviewed explicitly.

## Ownership and seven-day retention

The stable owner key is SHA-256 of `issuer + NUL + subject`, derived only after verification. Including the
issuer prevents two identity providers with the same subject from sharing a workspace.
Products have a non-null indexed `owner_id` and nullable indexed `expires_at`. Reviews, analysis snapshots
and optional AI records inherit ownership/expiry through their product foreign key. Foreign run IDs cannot
be selected under an owned product. Owner/expiry checks run in shared service queries, including history
and deletion; creation and collection derive identity from the server-side DB request context.

Account products expire seven days after creation. Refreshing, adding reviews, changing metadata and
re-analysis cannot renew this deadline. All original reviews and historical snapshots share this fixed
product deadline; new products can still be created by the same persistent account after earlier data expires.
Local products do not expire. Missing-expiry account rows fail closed rather than becoming permanent data.

Access expiry is immediate on subsequent requests; physical deletion is separate. An operator can run,
from `backend/`, against the intended `DATABASE_URL`:

```bash
.venv/bin/python scripts/purge_expired_data.py
```

This deletes expired products and uses foreign-key cascades to remove original reviews, snapshots and
optional AI records together. It does not delete identity-provider accounts or non-expiring local records.
The collector also clears the current owner's expired products before a new collection, avoiding conflicts
with the per-owner source index. A scheduler, operational monitoring and backup/log expiration are **not yet
implemented**. Seven-day deletion compliance is therefore not complete and public deployment remains blocked.
SQLite free pages, WAL files, migration backups and provider backups need an approved erasure/retention policy.

## Migration implications

SQLite migration 6 adds owner and expiry columns/indexes and rebuilds collected-product uniqueness as
`(owner_id, source_site, external_product_id, source_region)`. Existing records keep `owner_id=local`,
`expires_at=NULL`; their review data and analysis snapshots are not rewritten or reassigned to any account.
Use a new empty public database later rather than uploading local records. No real database was migrated
while developing this checkpoint: tests use temporary databases.

The subsequent [Phase 2B.1 migration foundation](POSTGRESQL_MIGRATION.md) adds a PostgreSQL driver, explicit
Alembic history, bounded pooling, UTC handling and job-retention relationships while preserving SQLite.
Local PostgreSQL 17.12 integration has been verified; no managed provider has been provisioned or validated.
Existing databases require explicit
stopped-app migrations; never change DATABASE_URL to a live service and assume compatibility. Supabase Auth
can be adopted independently of the database; both still require separately approved integration testing.

## Frontend boundary

`setAccessTokenProvider(async () => currentAccessToken)` supplies a current/refreshed token per API request,
including uploads and PDF/CSV downloads. Missing sessions and provider errors fail before network access
without being mislabelled as backend downtime. With no provider installed, existing local calls are unchanged.
Static-demo mode never invokes this hook or makes API/identity calls.

The local frontend session checkpoint adds a provider-independent controller and minimal sign-in/sign-out UI.
`VITE_AUTH_MODE=local` (default) preserves the existing local app. `VITE_AUTH_MODE=hosted` gates all dashboard
views during restoration, while signed out and after expiry/refresh failure. Other non-local values also
fail closed. Without valid public provider configuration, hosted builds display a disabled,
explicitly unconfigured sign-in screen. No live project is connected. Fake identities exist only in offline tests.

See [Frontend sessions](FRONTEND_SESSIONS.md) for the adapter contract and account-switch protections.
The subsequent [Supabase adapter](SUPABASE_AUTH.md) adds an SDK with explicit PKCE and persistence settings.
Persistent session storage belongs to that SDK, rather than custom password storage; the live service has not
been connected or validated in this checkpoint.

## Deterministic offline testing

`tests/test_auth.py` generates explicitly test-only signing keys in memory from public test seeds/scalars.
Only public JWKS files are written to pytest's temporary directories. No private PEM, production secret,
live Supabase credential or real review data is stored in the repository. These identities/keys must never
be configured for a public environment. JWT-mode tests use separate synthetic Alice/Bob subjects, real
signature verification and temporary SQLite databases. Remote key retrieval is mocked, including rotation,
cache behavior and failure; no Supabase or Apple network request is needed for these regressions.

```bash
# From backend/
.venv/bin/python -m pytest tests/test_auth.py tests/test_ownership.py tests/test_migrations.py
# From frontend/
npm test -- src/test/auth.test.js src/test/session.test.js src/test/sessionUi.test.jsx src/test/staticDemo.test.jsx
```

The existing suite also has an opt-in/live-local Ollama availability test; it skips if the configured model
is not running. No hosted resource benchmark or new model performance claim is made in this phase.

## Later Supabase configuration (not executed)

After separate approval, select an available India region if the service/plan supports it, then configure
persistent accounts, sign-up/email verification, site URL and exact callback allowlist, token lifetime,
and asymmetric signing keys. Do not enable anonymous sign-in for this persistent-account application.
Configure backend environment variables (read at process startup; no automatic `.env` loading):

```text
AUTH_MODE=jwt
AUTH_ISSUER=https://<project-ref>.supabase.co/auth/v1
AUTH_AUDIENCE=authenticated
AUTH_ALGORITHM=ES256
AUTH_JWKS_URL=https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json
AUTH_JWKS_FILE=
CORS_ORIGINS=https://<approved-frontend-origin>
AI_SUMMARIES=off
```

The configured algorithm must match the project's actual signing keys. Legacy shared-secret signing is not
accepted. The frontend may later receive its public project URL and publishable key; never expose a service-role
key, private signing key or database password in VITE_* variables. No live credentials are required now.
See [Supabase JWT guidance](https://supabase.com/docs/guides/auth/jwts),
[signing keys](https://supabase.com/docs/guides/auth/signing-keys) and
[PyJWT verification guidance](https://pyjwt.readthedocs.io/en/stable/usage.html).

If application tables are ever created inside Supabase, keep them out of unauthenticated Data API access.
Use a non-exposed schema or tested RLS/grants; the backend's SQLAlchemy owner filters do not protect a separate
browser-to-database API. Do not connect with a broadly privileged service role as a substitute for authorization.

## Remaining blockers and next checkpoint

The subsequent [Phase 2A.3 Supabase adapter](SUPABASE_AUTH.md) implements the managed-provider mapping
locally against a mocked SDK, including public configuration validation, callbacks and recovery UI.
No live identity project is connected. Review its persistence/revocation policy and remaining public-service
controls before any approved real-provider integration; no cloud creation or deployment is authorized here.

Other blockers remain: PostgreSQL compatibility/RLS, scheduled seven-day purge and backup retention, upload/body/
ZIP limits, server-side rate limiting/abuse protection, processing isolation and quotas, Linux memory/cold-start
benchmarks, production deployment configuration and operational monitoring. No paid service is approved, and no
claim is made that Render Free can run the ONNX workload reliably. Hosting selection remains unapproved.

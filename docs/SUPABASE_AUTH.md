# Phase 2A.3: Supabase authentication adapter

Local preparation only: no Supabase project has been created or connected, and no deployment is approved by
this checkpoint. All integration tests mock the SDK. Persistent accounts belong to the identity provider;
the seven-day application-data lifetime does not delete user identities.

The subsequent [Phase 2A.4 hardening review](AUTH_SECURITY_REVIEW.md) adds a server-enforced password-AMR
policy and isolates password mutations. Its findings and current validation supersede the historical
Phase 2A.3 results below.

## SDK and architecture

The frontend pins `@supabase/supabase-js` **2.119.0** (Node >=22). `supabaseAuth.js` maps its Auth API to the
existing provider-independent session controller. `SupabaseEntry` validates public configuration before
lazily importing the SDK. A missing/invalid configuration leaves hosted mode on a disabled, explicitly
unconfigured sign-in screen. Local mode and static-demo mode never initialize the provider.

The client uses `flowType: 'pkce'`, `persistSession: true`, `detectSessionInUrl: false` and
`autoRefreshToken: false`. The controller controls expiry refresh; SDK `getSession` can also refresh a stored
session as part of its own restoration behavior. API calls and PDF/CSV downloads continue obtaining the
current bearer token per request. Frontend identity metadata never authorizes backend data access.

The adapter subscribes once to SDK auth events and unsubscribes/disposes on teardown. Its event callback is
synchronous and does not await other SDK methods. Identical event payloads are deduplicated; a token-rotation
event cannot change the account owner. Controller revisions and API request epochs reject stale results,
including ignored fetch cancellation. Sign-out clears local UI access immediately, waits for already-started
SDK mutations to settle, then calls SDK sign-out so a late SDK write cannot follow a completed sign-out.

## Flows

- Sign-in: `signInWithPassword({ email, password })`; controller receives normalized issuer, subject,
  token and expiry. Passwords are passed directly, cleared from forms and never stored by application code.
- Registration: `signUp` with the fixed same-origin `/auth/confirm` redirect. Show generic confirmation
  messaging that does not claim the email exists or the account is already confirmed. Email confirmation
  must be enabled; an immediate signup session is signed out and treated as a configuration failure.
- Restoration: `getSession`; refresh uses `refreshSession`. Failed/expired sessions gate private views.
  `SIGNED_OUT` events remove the workspace; current-token backend 401s also clear the controller.
- Confirmation: capture the PKCE code on `/auth/confirm`, remove query/hash content from browser history,
  then use `exchangeCodeForSession`, preserving a validated optional SDK `sb_flow_id` selector.
  Duplicate codes, implicit token fragments, error callbacks and codes
  on unexpected paths fail closed. The SDK validates the stored PKCE verifier and one-use code.
  Confirmation-only sessions are signed out; users must perform a fresh password sign-in before data access.
- Reset request: `resetPasswordForEmail` with `/auth/recovery`; show a generic email-sent explanation.
- Recovery: exchange the PKCE code, honor SDK `redirectType: 'recovery'` / `PASSWORD_RECOVERY`, and show
  only the password-update form. A non-secret recovery-owner marker survives reload in localStorage.
  Recovery-mode changes invalidate private requests even when the account subject stays the same.
  Before `updateUser({ password })`, `getUser` must still identify the recovery owner. The mutation uses
  an isolated SDK client with `persistSession: false`, bound to the captured recovery credentials, so a
  shared-storage account switch cannot redirect the password update. The isolated client is disposed after
  success or failure. The UI requires
  at least 12 characters; the provider must enforce the actual production password policy. After success,
  sign out locally and require a new sign-in. Cancelling recovery also signs out.

PKCE email links must be opened in the browser/profile that initiated the flow and retains its verifier.
Links opened elsewhere, expired/used codes and missing storage fail safely; users request another email.
No user-controlled `next`, redirect origin or callback token is accepted. History/router isolation resets
private selections on login, logout, account switching and entry into recovery.

## Configuration for a later approved project

Frontend variables are public build-time values:

```text
VITE_AUTH_MODE=hosted
VITE_SUPABASE_URL=https://<project-ref>.supabase.co
VITE_SUPABASE_PUBLISHABLE_KEY=<modern sb_publishable_ client key>
VITE_API_URL=https://<approved-api-host>/api
```

Only HTTPS hosted-project URLs on `*.supabase.co` are accepted in this checkpoint; custom/self-hosted Auth
domains require a later explicit validation change. Only modern publishable keys are accepted. Legacy anon
JWT keys and `sb_secret_` keys are rejected; never put service-role keys, database credentials or signing
keys in frontend variables. A public key identifies the project; it is not user authorization.

The application derives exact redirects from its current origin, not request parameters. Later configure
the Supabase Site URL to the approved frontend origin and allow exactly:

```text
https://<approved-frontend-host>/auth/confirm
https://<approved-frontend-host>/auth/recovery
```

For an approved local development provider, use exact equivalents under `http://localhost:5173` separately.
HTTP is accepted only for loopback origins. Do not allow broad production preview wildcards. The frontend
host must serve the SPA for these direct callback paths. Configure an origin-only/no-referrer policy before
public use, and avoid analytics or third-party resources on callback pages. Codes are scrubbed when the
adapter starts; browser/proxy logs can still see the incoming URL before JavaScript runs.

Backend configuration remains explicit, as documented in [PHASE2A_SECURITY.md](PHASE2A_SECURITY.md):
`AUTH_MODE=jwt`, issuer exactly `<project-url>/auth/v1`, audience `authenticated`, and the project's actual
asymmetric signing algorithm and trusted HTTPS JWKS endpoint. Supabase user access tokens include `sub`,
`iss`, `aud`, `iat`, `exp` and `role`; backend tests exercise Supabase-style ES256 signatures. The existing
verifier supports an explicitly selected ES256, RS256 or EdDSA profile, rejects legacy HS256 and rejects
anonymous/service-role identities. Confirm actual project claims and keys later; do not weaken verification.
The publishable project key is never used as a backend signing secret.

## Persistence and security limitations

SDK-managed localStorage contains bearer/refresh credentials so sessions can survive browser restarts.
Application code stores only a non-secret recovery subject marker alongside it. XSS or a malicious browser
extension can steal these credentials; this SPA design does not provide HttpOnly cookie protection. CSP,
dependency maintenance, trusted frontend origins and an approved storage policy remain production work.
If that risk is unacceptable, evaluate a server/BFF cookie design in a separate checkpoint.

The recovery marker is UI protection, not server authorization. Supabase recovery tokens are authenticated
sessions; role/assurance level alone does not restrict them. Phase 2A.4 now requires signed password AMR and
rejects recovery AMR on every private data API, including exports. Missing/malformed AMR is denied. This
depends on the trusted provider retaining documented AMR semantics; see the hardening review for limitations.

SDK/local sign-out is not instantaneous JWT revocation. Offline backend verification can accept a previously
issued token until expiry. Local sign-out targets the current SDK session, not every device. Remote revocation
is observed through provider events, failed refresh or backend rejection; it is not continuously polled.
Provider failure/timeouts clear local UI access, but provider operations cannot universally be cancelled.
Disposing an SDK does not guarantee an already-started operation cannot finish writing session storage;
test actual multi-tab/provider behavior before public rollout. No live email delivery, recovery, revocation,
multi-tab browser persistence or project signing-key rotation has been validated here.

Database tables remain behind FastAPI. Do not expose them through Supabase Data API without independently
tested grants/RLS. PostgreSQL migration, scheduled seven-day deletion and backup retention, upload/ZIP/body
limits, quotas, rate limiting, processing isolation and hosting resource benchmarks remain blockers.

## Offline verification and later connection sequence

Historical Phase 2A.3 results: **231 frontend tests passed; 449 backend tests passed / 1 live-Ollama skip**.
Frontend lint, production/static-demo builds and bundle checks passed; an additional hosted build passed
its application bundle check. All ten static-demo files remain byte-identical to the prior baseline,
including when hosted-auth configuration is present. npm audit reports zero known advisories and changed-file
credential scans found no real credentials/private keys. At that checkpoint backend source and Pages workflows were unchanged.
The earlier 33 browser checks describe Phase 2A.2; new account actions are covered by mocked SDK and accessible
DOM tests here, not a real-provider browser/email-delivery audit.

Run `npm test`, `npm run lint`, both build commands and both bundle checks from `frontend/`; run
`.venv/bin/python -m pytest` from `backend/`. Tests use fake SDK sessions, test-only opaque tokens and
synthetic records. They cover registration, confirmation/recovery, refresh/expiry/failure, event deduplication,
account switching, stale responses, authenticated downloads and invalid configuration. No real provider calls
are permitted by these fixtures. See [FRONTEND_SESSIONS.md](FRONTEND_SESSIONS.md) for prior controller coverage.

After separate approval:

1. Approve the session-storage/recovery policy and public-service security controls.
2. Approve/create a free project in an available India region if the chosen plan offers it. No paid plan
   is implied. Keep production application data empty; never upload local real-user records.
3. Enable email confirmation, disable anonymous accounts, set password/email rate-limit policies and configure
   approved email delivery. Set exact Site URL and redirect allowlists; retain PKCE-compatible email templates.
4. Select asymmetric signing keys; configure and verify backend issuer/audience/algorithm/JWKS and exact CORS
   origin independently. Configure only the public project URL/key in a separate hosted frontend build.
5. Validate real disposable-account signup, confirmation, persistence, refresh, recovery, revocation, multi-tab
   sign-out and cross-user isolation in an approved test environment before enabling public access.
6. Complete the remaining backend/storage/deployment blockers before any public deployment. Preserve Pages.

API behavior was checked against the pinned installed SDK source and official documentation:
[Auth/session persistence](https://supabase.com/docs/reference/javascript/auth),
[auth events](https://supabase.com/docs/reference/javascript/auth-onauthstatechange),
[registration](https://supabase.com/docs/reference/javascript/auth-signup),
[PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow),
[password reset](https://supabase.com/docs/reference/javascript/auth-resetpasswordforemail),
[JWT claims](https://supabase.com/docs/guides/auth/jwts).

# Frontend sessions: local preparation checkpoint

This checkpoint prepares authentication locally. It does not provide production accounts, connect Supabase,
or make the application ready for an unprotected public deployment. Existing backend JWT verification and
ownership enforcement remain the authorization boundary; frontend identity metadata is never sent as an owner ID.

## Build modes and UI

- Default `VITE_AUTH_MODE=local`: existing local dashboard and API behavior are preserved.
- `VITE_AUTH_MODE=hosted`: dashboard views require a configured provider session. The current entrypoint has
  no real provider, so it shows an explicitly unconfigured form with disabled controls and sends no credentials.
  Unrecognized non-local values also gate access rather than silently enabling local mode.
- Vite `staticdemo` mode: the synthetic GitHub Pages demo ignores authentication configuration entirely.
  It makes no identity-provider or backend requests and remains independent of the session layer.

With an injected provider, the existing dashboard styling is retained. Sign-in uses labelled native email and
password fields, keyboard submission, loading states and generic error messages. Form values are cleared as
soon as submitted; credentials go directly to the provider. The account strip provides sign-out. Restoration
and expired-session refresh gate private content. Failed refresh or a current-token 401 returns to sign-in.

## Provider contract

`HostedApp` accepts a stable `provider` object. Every method may be asynchronous except subscription setup:

```js
getSession()                     // current canonical session or null
signIn({ email, password })      // resulting canonical session
signOut()                       // resolves after provider logout
refreshSession()                // refreshed canonical session or null
onSessionChange(listener)       // subscribe; returns unsubscribe function
```

Sessions have this normalized shape (expiry is absolute Unix time in milliseconds):

```js
{ issuer, user: { id, email }, accessToken, expiresAt }
```

The adapter must map its SDK into this contract, including canonical session-change events for account
switches, logout and token rotation. It must not emit obsolete snapshots from earlier asynchronous operations.
The controller guards its own delayed method results with revision numbers and suppresses unsolicited late
events after explicit logout or failed refresh until another explicit sign-in/start.

Tokens stay in the controller closure, outside rendered snapshots and browser storage. The API obtains the
current token per request through `setAccessTokenProvider`, including uploads and PDF/CSV downloads. Refresh
is deduplicated and occurs at expiry or when an expired token is requested. Provider operations have a ten-second
timeout. Missing/expired credentials never become an unauthenticated network request. No mutation is retried
automatically after a 401. A late 401 for a superseded token cannot sign out the refreshed session.

The future managed-provider SDK owns persistent sessions and refresh credentials. This controller does not
implement password storage, signing keys, accounts, browser-persisted tokens or a custom authentication service.
The deterministic in-memory provider in `src/test/helpers/fakeIdentity.js` is test-only. Its opaque fake tokens
cannot authenticate to the JWT backend and are excluded from application bundles.

## Account-switch isolation

The controller derives a UI identity from provider issuer and subject. Changing either, or signing out,
invalidates the API request epoch, aborts outstanding authenticated fetches and revokes pending download blob
URLs before rendering the next account. Requests recheck their epoch after token acquisition, fetch and body
parsing; ignored transport aborts cannot reintroduce old JSON or initiate a late download.

A keyed provider/router subtree remounts the existing dashboard without rewriting page state management.
It clears private product/analysis state, selected product/run IDs, comparison inputs, report selections and
download progress. The current URL is reset to `/`. Browser history entries receive an account scope; Back
to another scope's private path/query redirects to `/` before mounting that view. Tokens rotating for the
same account preserve the scope. Non-private display preferences in `rd-settings` remain unchanged.

Cancellation does not undo server work already accepted or retract a file already downloaded. Remote logout
failure still clears the local UI and reports that provider confirmation failed. Backend access tokens may
remain valid until expiry, as described in [the security checkpoint](PHASE2A_SECURITY.md).

## Verification

Baseline rechecked before edits: 449 backend tests passed / 1 live-Ollama skip; 153 frontend tests passed.
After this checkpoint: 193 frontend tests passed and 59 backend auth/ownership/migration tests passed.
The final continuation reran both full suites: 449 backend tests passed / 1 live-Ollama skip and
193 frontend tests passed. No application changes were needed, so the browser audit below was retained.
Frontend lint, production and static-demo builds and both bundle checks passed. An additional hosted-mode
production build passed its application bundle check. The ten static-demo output files are byte-identical
to the pre-checkpoint build, including with hosted authentication configuration present.

Offline tests cover restoration, sign-in/out, token expiry, refresh deduplication/failure/timeouts, StrictMode,
account switching, stale responses/body parsing, comparisons/history, report state, authenticated downloads,
local mode and static-demo isolation. A temporary loopback-only browser harness with synthetic fixtures passed
33 checks at 375, 768 and 1440 px, including keyboard interactions, account switching, overflow and axe checks
on sign-in and signed-in Overview. No browser errors, failed assets or unexpected network requests were recorded.
This is not a comprehensive accessibility certification or a live-provider integration test.

Final dependency checks: npm audit reported zero known advisories; Python `pip check` found no broken
requirements. The existing local node_modules tree reports six extraneous packages; manifests and lockfiles
were left unchanged. Python dependency consistency is not a Python vulnerability audit. Credential-pattern
and debug/conflict-marker scans of changed files found no matches; documentation relative links and
Markdown heading spacing passed. No production-provider or cloud deployment validation has been performed.

Run from `frontend/`:

```bash
npm test
npm run lint
npm run build
npm run check:app-bundle
npm run build:demo
npm run check:demo-bundle
```

From `backend/`:

```bash
.venv/bin/python -m pytest tests/test_auth.py tests/test_ownership.py tests/test_migrations.py
```

## Next checkpoint and limitations

Implement a provider-specific adapter using a mocked managed-provider SDK before any live connection. Validate
public configuration and session event ordering; specify persistent-session storage, refresh/revocation policy,
sign-up/email verification, recovery and exact callback allowlists. No Supabase project or credentials are needed
for that checkpoint. Only public provider configuration may enter VITE variables; never service-role credentials,
private signing keys or database passwords.

Public deployment remains blocked by the security/retention, database, upload protection, quotas, resource and
operational work listed in [PHASE2A_SECURITY.md](PHASE2A_SECURITY.md). No cloud services, deployment workflows,
backend behavior, real review records, commits or pushes are changed by this frontend checkpoint.

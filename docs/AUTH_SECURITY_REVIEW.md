# Phase 2A.4: authentication hardening and policy review

Local review only. Phase 2A.3 changes are preserved and extended; nothing is committed, pushed, deployed,
provisioned or connected to a real identity project. Application-data expiry remains seven days; identities
do not expire with reviews. No schema or data migration is performed.

## Findings and disposition

| Severity | Finding | Disposition |
|---|---|---|
| High | A valid recovery JWT previously satisfied the backend role check and could directly read/export/modify its owner's data despite the recovery UI gate. | Fixed for the supported signed password-AMR profile; all 24 private operations reject recovery tokens before parsing their bodies. |
| High | Shared-client `updateUser` reads its session asynchronously; another tab could switch the account after an earlier recovery identity check. | Password updates now use an isolated, non-persistent SDK session bound to captured credentials, with server `getUser` verification and account-generation checks. |
| Medium | A confirmation-only session mounted the dashboard without a password login. | Confirmation exchange now signs out that session; require fresh password sign-in. |
| Low | A refresh returning a recovery session could resolve the controller's direct token getter, although the API epoch check rejected the stale request. | The controller now rejects that token result too. |
| High, deployment blocker | XSS can steal SDK-persisted access/refresh credentials or issue actions as the user. | No HttpOnly protection is claimed. Approve the SPA storage risk and mitigations, or adopt the BFF design below before public use. |
| Medium, remaining | Offline JWT validation does not detect immediate logout/revocation; hanging SDK work can delay stored-session removal. | Documented; short access-token lifetimes and a server-controlled session design are required if immediate revocation is mandatory. |
| Low, remaining | Callback URLs initially reach browser/host logs before JavaScript scrubbing. | Require referrer/log policy and exact redirects at deployment; no secrets are logged by application code. |

Severity reflects impact if the hosted application were exposed. No public backend has been deployed here.

## Recovery JWT policy and its limits

Supabase's documented signed `amr` entries distinguish `password`, `recovery`, `email/signup`, `token_refresh`
and other methods. `role=authenticated`, `aal1`/`aal2`, subject, email confirmation, client route and the local
recovery marker do **not** establish password authentication. The Supabase Auth source also identifies
recovery sessions from their AMR history. No invented `is_recovery` claim or client-supplied completion flag
is accepted by FastAPI.

After signature, issuer, audience, role and timestamp verification, every private JWT-mode operation requires:

- A nonempty top-level signed `amr` array (maximum 32 entries).
- String methods and finite nonnegative numeric method timestamps no later than the JWT's `iat`.
- At least one `password` method and no `recovery` or `anonymous` method anywhere in the history.

Password plus MFA/refresh history is accepted; refreshing a recovery token does not grant password access.
Missing, malformed or recovery-contaminated AMR is rejected with the same generic 401/Bearer response as
other invalid credentials. This also rejects OAuth-only, signup-only, invitation, OTP and magic-link sessions.
Those authentication methods are outside this checkpoint's email/password data-access policy. Local loopback
mode remains unchanged. Public health/site metadata remains public.

**Provider compatibility is a deployment gate, not a proven live result.** AMR is not a universal guaranteed
JWT claim and these tests do not establish the behavior of a real Supabase project or custom token hook.
The policy deliberately denies missing evidence rather than guessing that missing recovery means password.
It trusts the configured issuer to preserve truthful documented AMR values. A hook that removes recovery
history while asserting password authentication would invalidate that assumption; do not configure such hooks.
Before public rollout, inspect actual signed password, confirmation, recovery and refreshed recovery tokens
with disposable accounts and verify server denials. Do not weaken validation to accommodate missing evidence.

If the provider cannot supply a trustworthy distinction, do not expose private APIs to arbitrary Supabase
bearer tokens. Use a server/BFF that exchanges recovery codes in a separate recovery-only session, exposes
only password-reset operations there, and creates an application session only after a separately verified
password login. Store provider tokens server-side; the browser receives an opaque Secure/HttpOnly/SameSite
cookie. Add CSRF/origin protection, session rotation, expiry, revocation and server-side grant checks. This
alternative is proposed, not implemented or provisioned by this checkpoint.

## Password-update account binding

The adapter verifies the current recovery owner through Supabase `getUser`, captures the SDK session and
checks that no auth event changed its generation. A fresh SDK client uses that captured access/refresh pair,
`persistSession: false`, `autoRefreshToken: false`, disabled URL detection and a unique in-memory storage key.
It verifies its own user again before `updateUser`. A switch before mutation aborts the operation; a switch
during the request cannot retarget that already bound SDK session. Late results do not clear or sign out the
new account. The isolated client is disposed on both success and failure. No custom credential localStorage
entry is introduced; credentials remain under SDK management.

Changing the password is an external mutation: an already accepted update cannot be undone by client
cancellation. The isolated operation can legitimately finish for the original owner after a tab switches
accounts; its result is discarded. Backend ownership still derives only from verified issuer/subject.

## Persistence and logout review

The pinned SDK is `@supabase/supabase-js` / Auth JS 2.119.0. Its persistent client serializes the session,
including access and refresh credentials, using its storage adapter. Refresh rotation updates that SDK-owned
session. The application does not copy credentials into another localStorage/sessionStorage record; its
custom recovery marker contains only a subject identifier and cannot authorize an API request.

With `scope: 'local'`, the pinned SDK removes the current stored session and emits `SIGNED_OUT` before its
best-effort revocation call, once its session-loading step completes. Its source explicitly treats some
401/403/404 responses as already signed out; a success return is not evidence that a server-side session was
revoked. The adapter first invalidates local UI/token access and waits for previously started SDK mutations,
preventing a delayed successful sign-in from writing credentials after a *completed* sign-out. If those SDK
operations hang, the controller times out and reports unconfirmed remote sign-out, but a reload may still
find persisted credentials before removal completes. No promise of immediate, cross-device logout is made.
Disposal is not universal cancellation of SDK network/storage work. A BFF is the stronger alternative.

Before public use: approve the storage policy; enforce a restrictive CSP and trusted script dependencies,
avoid HTML injection and third-party analytics on auth pages, maintain dependency audits, set appropriate
referrer/security headers, require TLS and exact origins, and keep debug/token logging off. CSP reduces
exposure but cannot make localStorage HttpOnly or eliminate all XSS. No deployment header is changed here.

## Callback review

Only `/auth/confirm` and `/auth/recovery` consume PKCE codes. Configuration requires a validated hosted
Supabase HTTPS URL and modern public client key; privileged/legacy JWT keys and unknown auth modes fail closed.
The entrypoint captures callback data once, scrubs it before lazy SDK loading, and preserves it through
StrictMode setup. Incomplete configuration also scrubs callback URL content without initializing a client.
Exchange uses a validated optional `sb_flow_id` selector; duplicate/empty codes, malformed/duplicate selectors,
implicit token fragments, error callbacks and codes on other paths are rejected. Concurrent restoration
shares one exchange; subsequent reads do not reuse the code. Expired/used codes rely on provider PKCE/code
verification, tested with mocked failures. Incoming `next`/`redirect_to` fields are never followed.

Recovery uses the callback path and SDK recovery result/event to gate the UI, but server AMR verification is
the real data-access check. Confirmation-only credentials are signed out. SDK event generations, controller
revisions, keyed dashboard state, history scopes and API epochs protect account switches and ignored fetch
aborts. The signed-token backend tests remain effective even if a browser's recovery marker is removed or
client flags are forged. Fixed same-origin redirects still need exact provider allowlists and SPA routing;
the allowed origin is public build configuration, not an attacker-supplied query parameter.

## JWT compatibility and operational requirements

The existing verifier pins issuer, audience, algorithm and operator-configured public JWKS. Offline tests cover
ES256, RS256 and EdDSA, expired/forged/unsigned/HS256 tokens, anonymous/service-role roles, duplicate headers,
untrusted key URLs, key use, rotation, configuration failure and JWKS outages. Signed subject and issuer alone
derive ownership; caller IDs and metadata never override it. Missing configuration fails startup in JWT mode;
unavailable required keys fail requests closed rather than enabling local mode.

Remote public keys have a five-minute cache and a 30-second refresh cooldown; cached still-valid keys may
continue verification during an outage. New-key recognition can be delayed by cooldown; revoked-key removal
can be delayed by cache lifetime. Publish overlapping keys for normal rotation and plan cache/restart handling
for emergency revocation. Public-key files require restart to rotate. No live key rotation has been performed.
Access tokens remain usable until expiry unless a separate online revocation/session gate is implemented.

## Validation and next checkpoint

Regression tests exercise recovery/refreshed recovery tokens against all 24 private operations, malformed
AMR and fake metadata, password+MFA/refresh, RSA key-use enforcement, confirmation logout, concurrent/invalid
callbacks, redirect injection, callback/logout races, password-update account binding, and recovery refresh
token rejection. Prior ownership, stale-response, protected-download, local and static-demo tests remain.
Dependency audits cover npm and the installed backend distribution versions using an isolated temporary
pip-audit tool; no audit tool or dependency upgrade is added to the project requirements.

Final validation: **470 backend tests passed / 1 live-Ollama skip; 242 frontend tests passed** (21 backend
and 11 frontend regressions added). Frontend lint, production and static-demo builds, both bundle checks
and an additional hosted-mode build/check passed. All ten static-demo output files are byte-identical to
the previously approved baseline, including with hosted-auth configuration present. npm reports zero known
advisories; pip-audit checked all 68 installed backend distributions, with zero known vulnerabilities and no
skipped packages. `git diff --check`, credential scans and documentation formatting/link checks passed.
These are offline code/SDK-mock checks, not live-provider or new browser/email-delivery verification.

Next checkpoint: approve SPA-versus-BFF session policy and the password-AMR compatibility gate; then implement
public API rate/size/processing quotas and scheduled seven-day physical deletion with backup/log retention.
Only after separate approval should disposable live-provider tests validate signing claims, email flows,
cross-tab behavior, logout and revocation. No cloud account, paid resource or deployment is authorized here.

Sources checked on 2026-11-15:
[Supabase JWT fields and AMR methods](https://supabase.com/docs/guides/auth/jwt-fields),
[Supabase recovery-session source](https://github.com/supabase/auth/blob/master/internal/models/sessions.go),
[Supabase PKCE/recovery verification source](https://github.com/supabase/auth/blob/master/internal/api/verify.go),
[SDK sign-out semantics](https://supabase.com/docs/reference/javascript/auth-signout),
[session lifecycle and refresh tokens](https://supabase.com/docs/guides/auth/sessions),
[Auth persistence](https://supabase.com/docs/reference/javascript/auth).
The mutable upstream sources are supporting evidence, not substitutes for testing an approved live project.

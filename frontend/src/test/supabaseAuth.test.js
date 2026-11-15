import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSupabaseAdapter, loadSupabaseAdapter, supabaseConfig } from '../lib/supabaseAuth'
import { createSessionController } from '../lib/session'
import { api, setAccessTokenProvider, invalidateAuthenticatedRequests } from '../lib/api'
import { deferred } from './helpers/fakeIdentity'
import { createElement, StrictMode } from 'react'
import { render, screen } from '@testing-library/react'
import App from '../App'

const sdkFactory = vi.hoisted(() => vi.fn())
vi.mock('@supabase/supabase-js', () => ({ createClient: sdkFactory }))
const env = { VITE_SUPABASE_URL: 'https://offline-test.supabase.co',
  VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_publishable_OFFLINE_TEST_NOT_A_REAL_KEY' }
const config = () => supabaseConfig(env, window.location.origin)
const sdkSession = (id = 'alice', extra = {}) => ({ access_token: `OFFLINE-SDK-${id}`,
  refresh_token: `OFFLINE-REFRESH-${id}`,
  expires_at: Math.floor(Date.now() / 1000) + 3600, user: { id, email: `${id}@example.invalid` }, ...extra })
let providers, controllers
function sdk(initial = null) {
  let session = initial, callback = () => {}
  const response = (data) => Promise.resolve({ data, error: null })
  const emit = (event, value) => { session = value; callback(event, value) }
  const auth = {
    getSession: vi.fn(() => response({ session })),
    getUser: vi.fn(() => response({ user: session?.user })),
    signInWithPassword: vi.fn(({ email }) => { emit('SIGNED_IN', sdkSession(email.split('@')[0])); return response({ session }) }),
    signUp: vi.fn(() => response({ user: { id: 'synthetic' }, session: null })),
    signOut: vi.fn(() => { emit('SIGNED_OUT', null); return response({}) }),
    refreshSession: vi.fn(() => { emit('TOKEN_REFRESHED', sdkSession(session.user.id, { access_token: 'OFFLINE-SDK-fresh' })); return response({ session }) }),
    exchangeCodeForSession: vi.fn(() => { emit('SIGNED_IN', sdkSession()); return response({ session, redirectType: null }) }),
    resetPasswordForEmail: vi.fn(() => response({})), updateUser: vi.fn(() => response({ user: session?.user })),
    dispose: vi.fn(),
    onAuthStateChange: vi.fn((listener) => { callback = listener; return { data: { subscription: { unsubscribe: vi.fn(() => { callback = () => {} }) } } } }),
  }
  let bound
  const recoveryAuth = {
    setSession: vi.fn(async (value) => { bound = sdkSession(value.access_token.replace('OFFLINE-SDK-', '')); return { data: { session: bound }, error: null } }),
    getUser: vi.fn(async () => ({ data: { user: bound?.user }, error: null })),
    updateUser: auth.updateUser, dispose: vi.fn(),
  }
  return { auth, emit, recoveryAuth, createRecoveryAuth: () => recoveryAuth }
}
function adapter(client, options) { const p = createSupabaseAdapter(client, config(), { createRecoveryAuth: client.createRecoveryAuth, ...options }); providers.push(p); return p }
async function controller(p) { const c = createSessionController(p, { onBoundary: invalidateAuthenticatedRequests }); controllers.push(c); await c.start(); return c }
beforeEach(() => { providers = []; controllers = []; localStorage.clear(); window.history.replaceState(null, '', '/'); sdkFactory.mockReset() })
afterEach(() => { controllers.forEach((c) => c.stop()); providers.forEach((p) => p.dispose()); setAccessTokenProvider(null); vi.restoreAllMocks(); vi.unstubAllEnvs() })

describe('validated public Supabase configuration', () => {
  it.each([
    {}, { ...env, VITE_SUPABASE_URL: 'http://offline-test.supabase.co' },
    { ...env, VITE_SUPABASE_URL: 'https://attacker.invalid' },
    { ...env, VITE_SUPABASE_URL: 'https://offline-test.supabase.co?redirect=evil' },
    { ...env, VITE_SUPABASE_PUBLISHABLE_KEY: 'sb_secret_NEVER_ALLOWED_TEST_STRING' },
    { ...env, VITE_SUPABASE_PUBLISHABLE_KEY: 'eyJ-not-a-real-legacy-key' },
  ])('rejects incomplete or unsafe configuration %#', (value) => {
    expect(() => supabaseConfig(value, window.location.origin)).toThrow()
    expect(sdkFactory).not.toHaveBeenCalled()
  })
  it('rejects insecure non-loopback application origins', () => {
    expect(() => supabaseConfig(env, 'http://public.example.invalid')).toThrow()
    expect(config().issuer).toBe('https://offline-test.supabase.co/auth/v1')
  })
  it('loads the pinned SDK with explicit PKCE, persistence and no automatic URL detection or refresh', async () => {
    const client = sdk(); sdkFactory.mockReturnValue(client)
    const p = await loadSupabaseAdapter(config()); providers.push(p)
    expect(sdkFactory).toHaveBeenCalledWith(config().url, env.VITE_SUPABASE_PUBLISHABLE_KEY, { auth: {
      flowType: 'pkce', persistSession: true, autoRefreshToken: false, detectSessionInUrl: false, storageKey: config().storageKey,
    } })
  })
  it('creates a separate non-persistent SDK client for password updates and disposes it', async () => {
    const client = sdk(sdkSession())
    localStorage.setItem(`${config().storageKey}-recovery`, 'alice')
    sdkFactory.mockReturnValueOnce(client).mockReturnValueOnce({ auth: client.recoveryAuth })
    const p = await loadSupabaseAdapter(config()); providers.push(p)
    await p.updatePassword('offline-new-password')
    expect(sdkFactory.mock.calls[1][2].auth).toMatchObject({ persistSession: false,
      autoRefreshToken: false, detectSessionInUrl: false })
    expect(client.recoveryAuth.setSession).toHaveBeenCalledWith({ access_token: 'OFFLINE-SDK-alice', refresh_token: 'OFFLINE-REFRESH-alice' })
    expect(client.recoveryAuth.dispose).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(localStorage)).not.toMatch(/OFFLINE-SDK|OFFLINE-REFRESH|password/)
  })
  it('never imports or initializes the SDK in a static-demo build', async () => {
    vi.stubEnv('MODE', 'staticdemo')
    await expect(loadSupabaseAdapter(config())).rejects.toThrow('static demo')
    expect(sdkFactory).not.toHaveBeenCalled()
  })
  it('wires a configured hosted entrypoint through the mocked SDK without any real service request', async () => {
    const client = sdk(); sdkFactory.mockReturnValue(client)
    vi.stubEnv('VITE_AUTH_MODE', 'hosted')
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value)
    globalThis.fetch = vi.fn()
    render(createElement(StrictMode, null, createElement(App)))
    await screen.findByRole('button', { name: 'Create an account' })
    expect(sdkFactory).toHaveBeenCalledTimes(1)
    expect(fetch).not.toHaveBeenCalled()
  })
  it('ignores unknown auth modes even if public project settings are present', () => {
    vi.stubEnv('VITE_AUTH_MODE', 'typo')
    for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value)
    render(createElement(App))
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
    expect(sdkFactory).not.toHaveBeenCalled()
  })
})

describe('Supabase identity adapter with offline SDK behavior', () => {
  it('registers without retaining credentials or claiming that confirmation has completed', async () => {
    const client = sdk(), p = adapter(client)
    expect(await p.register({ email: 'alice@example.invalid', password: 'offline-test-password' })).toMatch(/check your email/)
    expect(client.auth.signUp).toHaveBeenCalledWith({ email: 'alice@example.invalid', password: 'offline-test-password',
      options: { emailRedirectTo: `${window.location.origin}/auth/confirm` } })
    expect(await p.getSession()).toBeNull()
    expect(JSON.stringify(localStorage)).not.toContain('password')
  })
  it('fails closed if registration bypasses required email confirmation', async () => {
    const client = sdk(), p = adapter(client)
    client.auth.signUp.mockResolvedValue({ data: { session: sdkSession() }, error: null })
    await expect(p.register({})).rejects.toThrow('confirmation')
    expect(client.auth.signOut).toHaveBeenCalledWith({ scope: 'local' })
    expect(await p.getSession()).toBeNull()
  })
  it('signs in through SDK events, restores and signs out through the controller', async () => {
    const client = sdk(), p = adapter(client), c = await controller(p)
    await c.signIn({ email: 'alice@example.invalid', password: 'offline-test-password' })
    expect(c.getSnapshot()).toMatchObject({ status: 'signedIn', user: { id: 'alice' } })
    expect(await c.getAccessToken()).toBe('OFFLINE-SDK-alice')
    await c.signOut()
    expect(c.getSnapshot().status).toBe('signedOut')
    expect(await p.getSession()).toBeNull()
  })
  it('deduplicates identical events and handles account switches and revocation', async () => {
    const client = sdk(sdkSession()), p = adapter(client), c = await controller(p)
    const boundary = c.getSnapshot().epoch, listener = vi.fn()
    p.onSessionChange(listener)
    client.emit('SIGNED_IN', sdkSession())
    client.emit('SIGNED_IN', sdkSession())
    expect(listener).toHaveBeenCalledTimes(1)
    expect(c.getSnapshot().epoch).toBe(boundary)
    client.emit('SIGNED_IN', sdkSession('bob'))
    expect(c.getSnapshot().user.id).toBe('bob')
    expect(c.getSnapshot().epoch).toBe(boundary + 1)
    client.emit('SIGNED_OUT', null)
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
  })
  it('refreshes expired stored sessions while handling SDK TOKEN_REFRESHED notifications', async () => {
    const client = sdk(sdkSession('alice', { expires_at: 1 })), c = await controller(adapter(client))
    expect(c.getSnapshot().status).toBe('signedIn')
    expect(await c.getAccessToken()).toBe('OFFLINE-SDK-fresh')
    expect(client.auth.refreshSession).toHaveBeenCalledTimes(1)
  })
  it('clears an expired account when refresh fails without exposing SDK errors', async () => {
    const client = sdk(sdkSession('alice', { expires_at: 1 }))
    client.auth.refreshSession.mockResolvedValue({ data: { session: null }, error: new Error('sensitive details') })
    const c = await controller(adapter(client))
    expect(c.getSnapshot()).toMatchObject({ status: 'signedOut', user: null })
    expect(c.getSnapshot().error).toMatch(/session expired/)
    expect(c.getSnapshot().error).not.toContain('sensitive')
  })
  it('does not let a rejected old refresh sign out the new account', async () => {
    const pending = deferred(), client = sdk(sdkSession()), p = adapter(client)
    client.auth.refreshSession.mockReturnValue(pending.promise)
    const c = await controller(p), refresh = p.refreshSession().catch((e) => e)
    client.emit('SIGNED_IN', sdkSession('bob'))
    pending.resolve({ data: {}, error: new Error('late failure') })
    await refresh
    expect(await c.getAccessToken()).toBe('OFFLINE-SDK-bob')
    expect((await p.getSession()).user.id).toBe('bob')
  })
  it('ignores obsolete token-rotation events from a different account', async () => {
    const client = sdk(sdkSession()), c = await controller(adapter(client))
    client.emit('SIGNED_IN', sdkSession('bob'))
    client.emit('TOKEN_REFRESHED', sdkSession('alice'))
    expect(c.getSnapshot().user.id).toBe('bob')
    expect(await c.getAccessToken()).toBe('OFFLINE-SDK-bob')
  })
  it('does not resurrect a delayed sign-in after logout, and clears SDK storage last', async () => {
    const pending = deferred(), client = sdk(), p = adapter(client)
    client.auth.signInWithPassword.mockReturnValue(pending.promise)
    const login = p.signIn({}).catch((e) => e), logout = p.signOut()
    expect(client.auth.signOut).not.toHaveBeenCalled()
    pending.resolve({ data: { session: sdkSession() }, error: null })
    expect((await login).name).toBe('AbortError')
    await logout
    expect(await p.getSession()).toBeNull()
    expect(client.auth.signOut).toHaveBeenCalledTimes(1)
  })
  it('authenticates API reads and downloads and rejects ignored-abort stale data', async () => {
    const pending = deferred(), client = sdk(sdkSession()), c = await controller(adapter(client))
    setAccessTokenProvider(c.getAccessToken, { onUnauthorized: c.rejectAccessToken })
    globalThis.fetch = vi.fn().mockReturnValueOnce(pending.promise).mockResolvedValue(new Response(new Blob(['synthetic report'])))
    const request = api.listProducts().catch((e) => e)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    client.emit('SIGNED_IN', sdkSession('bob'))
    pending.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }))
    expect((await request).name).toBe('AbortError')
    URL.createObjectURL = vi.fn(() => 'blob:synthetic')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    await api.downloadReport(7, 'csv')
    expect(fetch.mock.calls[1][1].headers.Authorization).toBe('Bearer OFFLINE-SDK-bob')
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledTimes(1)
  })
})

describe('explicit PKCE callbacks', () => {
  it('shares concurrent callback exchanges and never reuses the captured code', async () => {
    window.history.replaceState(null, '', '/auth/recovery?code=OFFLINE-CODE')
    const pending = deferred(), client = sdk()
    client.auth.exchangeCodeForSession.mockReturnValue(pending.promise)
    const p = adapter(client), first = p.getSession(), second = p.getSession()
    expect(client.auth.exchangeCodeForSession).toHaveBeenCalledTimes(1)
    pending.resolve({ data: { session: sdkSession(), redirectType: 'recovery' }, error: null })
    expect((await first).user.id).toBe('alice')
    expect((await second).user.id).toBe('alice')
    await p.getSession()
    expect(client.auth.exchangeCodeForSession).toHaveBeenCalledTimes(1)
  })
  it.each(['/auth/confirm?code=valid&sb_flow_id=bad', '/auth/confirm?code=valid&sb_flow_id=OFFLINE_FLOW&sb_flow_id=OTHER_FLOW',
    '/auth/confirm?error=denied&code=valid', '/auth/confirm?code='])('rejects malformed flow selectors/error callbacks: %s', async (path) => {
    window.history.replaceState(null, '', path)
    const client = sdk(), c = await controller(adapter(client))
    expect(c.getSnapshot().status).toBe('signedOut')
    expect(client.auth.exchangeCodeForSession).not.toHaveBeenCalled()
  })
  it('never follows next/redirect parameters supplied to a valid callback', async () => {
    window.history.replaceState(null, '', '/auth/confirm?code=OFFLINE-CODE&next=https://attacker.invalid&redirect_to=https://attacker.invalid')
    const client = sdk(), c = await controller(adapter(client))
    expect(c.getSnapshot().status).toBe('signedOut')
    expect(window.location.origin).toBe(config().origin)
    expect(window.location.search).toBe('')
    expect(client.auth.signOut).toHaveBeenCalledWith({ scope: 'local' })
  })
  it('never exposes a recovery callback that finishes after sign-out', async () => {
    window.history.replaceState(null, '', '/auth/recovery?code=OFFLINE-CODE')
    const pending = deferred(), client = sdk()
    client.auth.exchangeCodeForSession.mockReturnValue(pending.promise)
    const p = adapter(client), c = createSessionController(p)
    controllers.push(c)
    const starting = c.start()
    await vi.waitFor(() => expect(client.auth.exchangeCodeForSession).toHaveBeenCalled())
    const logout = c.signOut()
    pending.resolve({ data: { session: sdkSession(), redirectType: 'recovery' }, error: null })
    await Promise.all([starting, logout])
    expect(c.getSnapshot().status).toBe('signedOut')
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
    expect(client.auth.signOut).toHaveBeenCalledTimes(1)
  })
  it('isolates password mutation from account switching and discards its late completion', async () => {
    localStorage.setItem(`${config().storageKey}-recovery`, 'alice')
    const client = sdk(sdkSession()), pending = deferred(), p = adapter(client)
    const c = await controller(p)
    client.recoveryAuth.updateUser.mockReturnValue(pending.promise)
    const update = p.updatePassword('offline-new-password').catch((e) => e)
    await vi.waitFor(() => expect(client.recoveryAuth.updateUser).toHaveBeenCalled())
    expect(client.recoveryAuth.setSession).toHaveBeenCalledWith({ access_token: 'OFFLINE-SDK-alice', refresh_token: 'OFFLINE-REFRESH-alice' })
    client.emit('SIGNED_IN', sdkSession('bob'))
    pending.resolve({ data: { user: { id: 'alice' } }, error: null })
    expect((await update).message).toMatch(/account changed/)
    expect(c.getSnapshot().user.id).toBe('bob')
    expect(client.auth.signOut).not.toHaveBeenCalled()
    expect(client.recoveryAuth.dispose).toHaveBeenCalledTimes(1)
  })
  it('does not mutate after an account switch during recovery verification', async () => {
    localStorage.setItem(`${config().storageKey}-recovery`, 'alice')
    const client = sdk(sdkSession()), pending = deferred(), p = adapter(client)
    client.auth.getUser.mockReturnValue(pending.promise)
    const c = await controller(p), update = p.updatePassword('offline-new-password').catch((e) => e)
    client.emit('SIGNED_IN', sdkSession('bob'))
    pending.resolve({ data: { user: { id: 'alice' } }, error: null })
    expect((await update).message).toMatch(/account changed/)
    expect(c.getSnapshot().user.id).toBe('bob')
    expect(client.recoveryAuth.updateUser).not.toHaveBeenCalled()
  })
  it('preserves the SDK flow selector while scrubbing it from browser history', async () => {
    window.history.replaceState(null, '', '/auth/confirm?code=OFFLINE-CODE&sb_flow_id=OFFLINE_FLOW_123')
    const client = sdk(), p = adapter(client)
    await controller(p)
    expect(client.auth.exchangeCodeForSession).toHaveBeenCalledWith('OFFLINE-CODE', { flowId: 'OFFLINE_FLOW_123' })
    expect(window.location.search).toBe('')
  })
  it.each(['/auth/confirm', '/auth/recovery'])('scrubs and consumes %s exactly once', async (path) => {
    window.history.replaceState(null, '', `${path}?code=OFFLINE-CODE`)
    const client = sdk(), p = adapter(client)
    expect(window.location.search).toBe('')
    const c = await controller(p)
    expect(client.auth.exchangeCodeForSession).toHaveBeenCalledWith('OFFLINE-CODE')
    expect(c.getSnapshot().status).toBe(path.endsWith('recovery') ? 'recovery' : 'signedOut')
    if (path.endsWith('recovery')) {
      await expect(c.getAccessToken()).rejects.toThrow('Sign in')
      await p.updatePassword('offline-new-password')
      expect(client.auth.updateUser).toHaveBeenCalledWith({ password: 'offline-new-password' })
      expect(c.getSnapshot().status).toBe('signedOut')
    }
  })
  it('preserves recovery gating across page restoration and SDK token rotation', async () => {
    localStorage.setItem(`${config().storageKey}-recovery`, 'alice')
    const client = sdk(sdkSession()), c = await controller(adapter(client))
    client.emit('TOKEN_REFRESHED', sdkSession('alice', { access_token: 'OFFLINE-SDK-new' }))
    expect(c.getSnapshot().status).toBe('recovery')
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
  })
  it('invalidates private requests when an existing account enters recovery', async () => {
    const client = sdk(sdkSession()), c = await controller(adapter(client))
    const epoch = c.getSnapshot().epoch
    client.emit('PASSWORD_RECOVERY', sdkSession())
    expect(c.getSnapshot()).toMatchObject({ status: 'recovery', epoch: epoch + 1 })
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
  })
  it('checks the recovery identity again before updating a password', async () => {
    localStorage.setItem(`${config().storageKey}-recovery`, 'alice')
    const client = sdk(sdkSession('bob')), p = adapter(client)
    await expect(p.updatePassword('offline-new-password')).rejects.toThrow('recovery account changed')
    expect(client.auth.updateUser).not.toHaveBeenCalled()
  })
  it.each(['/auth/confirm?code=a&code=b', '/auth/recovery#error=denied', '/auth/confirm#access_token=TEST', '/wrong?code=a'])('rejects malformed/implicit callback %s', async (url) => {
    window.history.replaceState(null, '', url)
    const client = sdk(), c = await controller(adapter(client))
    expect(c.getSnapshot().status).toBe('signedOut')
    expect(client.auth.exchangeCodeForSession).not.toHaveBeenCalled()
    expect(window.location.search + window.location.hash).toBe('')
  })
  it('rejects expired/used callback codes with a safe restoration error', async () => {
    window.history.replaceState(null, '', '/auth/confirm?code=OFFLINE-USED')
    const client = sdk()
    client.auth.exchangeCodeForSession.mockResolvedValue({ data: {}, error: new Error('secret provider failure') })
    const c = await controller(adapter(client))
    expect(c.getSnapshot()).toMatchObject({ status: 'signedOut', error: 'Couldn’t restore your session. Sign in again.' })
  })
  it('uses a fixed same-origin recovery redirect and does not reveal account existence', async () => {
    const client = sdk(), p = adapter(client)
    expect(await p.requestPasswordReset('alice@example.invalid')).toMatch(/If an account matches/)
    expect(client.auth.resetPasswordForEmail).toHaveBeenCalledWith('alice@example.invalid', { redirectTo: `${window.location.origin}/auth/recovery` })
    await expect(p.updatePassword('offline-new-password')).rejects.toThrow('valid password reset')
  })
})

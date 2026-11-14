import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createSessionController } from '../lib/session'
import { deferred, fakeProvider, fakeSession } from './helpers/fakeIdentity'

let controllers
function controller(provider, options) {
  const result = createSessionController(provider, options)
  controllers.push(result)
  return result
}
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(new Date('2026-01-01T00:00:00Z')); controllers = [] })
afterEach(() => { for (const c of controllers) c.stop(); vi.useRealTimers() })

async function settle() { await vi.advanceTimersByTimeAsync(0) }

describe('managed-provider session adapter, offline', () => {
  it('fails closed without a complete configured provider', async () => {
    const c = controller(null)
    await c.start()
    expect(c.getSnapshot().status).toBe('unconfigured')
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
  })

  it('restores an existing account and never publishes access tokens in React state', async () => {
    const c = controller(fakeProvider(fakeSession()))
    await c.start()
    expect(c.getSnapshot()).toMatchObject({ status: 'signedIn', user: { id: 'alice' } })
    expect(JSON.stringify(c.getSnapshot())).not.toContain('OFFLINE-TEST')
    expect(await c.getAccessToken()).toBe('OFFLINE-TEST-alice-1')
  })

  it('signs in and signs out through the provider without writing browser storage', async () => {
    const local = vi.spyOn(Storage.prototype, 'setItem')
    const p = fakeProvider()
    const c = controller(p)
    await c.start()
    await c.signIn({ email: 'alice@example.invalid', password: 'offline-test-password' })
    expect(c.getSnapshot().status).toBe('signedIn')
    await c.signOut()
    expect(c.getSnapshot()).toMatchObject({ status: 'signedOut', user: null })
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
    expect(local).not.toHaveBeenCalled()
    local.mockRestore()
  })

  it('blocks stale restoration from overwriting a newer sign-in', async () => {
    const pending = deferred()
    const p = fakeProvider()
    p.getSession = () => pending.promise
    const c = controller(p)
    const restore = c.start()
    await c.signIn({ email: 'bob@example.invalid', password: 'offline-test-password' })
    pending.resolve(fakeSession('alice'))
    await restore
    expect(c.getSnapshot().user.id).toBe('bob')
  })

  it('does not resurrect a pending sign-in after sign-out, including a late provider event', async () => {
    const pending = deferred()
    const p = fakeProvider()
    p.signIn = () => pending.promise
    const c = controller(p)
    await c.start()
    const signingIn = c.signIn({ email: 'alice@example.invalid', password: 'offline-test-password' })
    await c.signOut()
    p.change(fakeSession('alice'))
    pending.resolve(fakeSession('alice'))
    await signingIn
    expect(c.getSnapshot().status).toBe('signedOut')
  })

  it('restores an expired session only after successful provider refresh', async () => {
    const pending = deferred()
    const p = fakeProvider(fakeSession('alice', { expiresAt: Date.now() - 1 }))
    p.refreshSession = () => pending.promise
    const c = controller(p)
    const start = c.start()
    await settle()
    expect(c.getSnapshot().status).toBe('restoring')
    pending.resolve(fakeSession('alice', { token: 'OFFLINE-TEST-fresh' }))
    await start
    expect(c.getSnapshot().status).toBe('signedIn')
    expect(await c.getAccessToken()).toBe('OFFLINE-TEST-fresh')
  })

  it('refreshes on expiry, shares concurrent refresh requests and hides private content during refresh', async () => {
    const pending = deferred()
    const p = fakeProvider(fakeSession('alice', { expiresAt: Date.now() + 1000 }))
    p.refreshSession = vi.fn(() => pending.promise)
    const c = controller(p)
    await c.start()
    const epoch = c.getSnapshot().epoch
    await vi.advanceTimersByTimeAsync(1000)
    const a = c.getAccessToken(), b = c.getAccessToken()
    expect(c.getSnapshot().status).toBe('restoring')
    pending.resolve(fakeSession('alice', { token: 'OFFLINE-TEST-refreshed' }))
    expect(await a).toBe('OFFLINE-TEST-refreshed')
    expect(await b).toBe('OFFLINE-TEST-refreshed')
    expect(p.refreshSession).toHaveBeenCalledTimes(1)
    expect(c.getSnapshot()).toMatchObject({ status: 'signedIn', epoch })
  })

  it.each(['reject', 'null', 'expired', 'malformed'])('fails closed on %s refresh', async (kind) => {
    const p = fakeProvider(fakeSession('alice', { expiresAt: Date.now() + 1 }))
    p.refreshSession = async () => {
      if (kind === 'reject') throw new Error('provider internal details')
      return kind === 'null' ? null : kind === 'malformed' ? {} : fakeSession('alice', { expiresAt: 1 })
    }
    const c = controller(p)
    await c.start()
    await vi.advanceTimersByTimeAsync(2)
    expect(c.getSnapshot()).toMatchObject({ status: 'signedOut', user: null })
    expect(c.getSnapshot().error).toMatch(/session expired.*Sign in again/)
    expect(c.getSnapshot().error).not.toContain('internal')
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
  })

  it('times out a hanging refresh and ignores its later completion', async () => {
    const pending = deferred()
    const p = fakeProvider(fakeSession('alice', { expiresAt: Date.now() + 1 }))
    p.refreshSession = () => pending.promise
    const c = controller(p, { timeoutMs: 100 })
    await c.start()
    await vi.advanceTimersByTimeAsync(102)
    expect(c.getSnapshot().status).toBe('signedOut')
    pending.resolve(fakeSession())
    await settle()
    expect(c.getSnapshot().status).toBe('signedOut')
  })

  it('cancels the old token waiter when accounts change during refresh', async () => {
    const pending = deferred()
    const p = fakeProvider(fakeSession('alice', { expiresAt: Date.now() + 1 }))
    p.refreshSession = () => pending.promise
    const c = controller(p)
    await c.start()
    vi.setSystemTime(Date.now() + 2)
    const token = c.getAccessToken().catch((e) => e)
    p.change(fakeSession('bob'))
    pending.resolve(fakeSession('alice'))
    expect((await token).name).toBe('AbortError')
    expect(c.getSnapshot().user.id).toBe('bob')
    expect(await c.getAccessToken()).toBe('OFFLINE-TEST-bob-1')
  })

  it('isolates issuer changes but preserves private UI scope on same-account token rotation', async () => {
    const boundary = vi.fn()
    const p = fakeProvider(fakeSession())
    const c = controller(p, { onBoundary: boundary })
    await c.start()
    const epoch = c.getSnapshot().epoch
    p.change(fakeSession('alice', { token: 'OFFLINE-TEST-new-token' }))
    expect(c.getSnapshot().epoch).toBe(epoch)
    p.change(fakeSession('alice', { issuer: 'https://another-test-identity.invalid' }))
    expect(c.getSnapshot().epoch).toBe(epoch + 1)
    expect(boundary).toHaveBeenCalledTimes(2)
  })

  it('ignores a late rejection of a previous token but rejects the current token', async () => {
    const p = fakeProvider(fakeSession())
    const c = controller(p)
    await c.start()
    p.change(fakeSession('alice', { token: 'OFFLINE-TEST-new-token' }))
    c.rejectAccessToken('OFFLINE-TEST-alice-1')
    expect(c.getSnapshot().status).toBe('signedIn')
    c.rejectAccessToken('OFFLINE-TEST-new-token')
    expect(c.getSnapshot().status).toBe('signedOut')
  })

  it('clears the local session before remote sign-out completes or fails', async () => {
    const pending = deferred()
    const p = fakeProvider(fakeSession())
    p.signOut = () => pending.promise
    const c = controller(p)
    await c.start()
    const out = c.signOut()
    expect(c.getSnapshot()).toMatchObject({ status: 'signingOut', user: null })
    await expect(c.getAccessToken()).rejects.toThrow('Sign in')
    pending.reject(new Error('internal provider error'))
    await out
    expect(c.getSnapshot().status).toBe('signedOut')
    expect(c.getSnapshot().error).toMatch(/Signed out on this device/)
  })

  it('unsubscribes, cancels timers and tolerates start/stop/start used by StrictMode', async () => {
    const p = fakeProvider(fakeSession())
    const c = controller(p)
    await c.start()
    c.stop()
    expect(p.listenerCount()).toBe(0)
    await c.start()
    expect(p.listenerCount()).toBe(1)
    expect(c.getSnapshot().status).toBe('signedIn')
    c.stop()
    expect(vi.getTimerCount()).toBe(0)
  })
})

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, invalidateAuthenticatedRequests, setAccessTokenProvider } from '../lib/api'
import { deferred } from './helpers/fakeIdentity'

beforeEach(() => { globalThis.fetch = vi.fn(() => Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }))) })
afterEach(() => { setAccessTokenProvider(null); vi.restoreAllMocks() })

describe('access-token transport', () => {
  it('keeps local requests unchanged without an identity provider', async () => {
    await api.listProducts()
    expect(fetch).toHaveBeenCalledWith(`${api.baseUrl}/products`, {})
  })

  it('requests a current token each time and preserves JSON headers', async () => {
    const provider = vi.fn().mockResolvedValueOnce('test-access-token-1').mockResolvedValueOnce('test-access-token-2')
    setAccessTokenProvider(provider)
    await api.listProducts()
    await api.analyzeUrl('https://demo.reviewsdekho.test/product/kestrel-orbit-5g')
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer test-access-token-1')
    expect(fetch.mock.calls[1][1].headers).toEqual({ 'Content-Type': 'application/json', Authorization: 'Bearer test-access-token-2' })
  })

  it('authenticates uploads without forcing a multipart content-type', async () => {
    setAccessTokenProvider(() => 'test-access-token')
    await api.previewUpload(new File(['review\nExcellent'], 'synthetic.csv'))
    expect(fetch.mock.calls[0][1].headers).toEqual({ Authorization: 'Bearer test-access-token' })
    expect(fetch.mock.calls[0][1].body).toBeInstanceOf(FormData)
  })

  it.each(['pdf', 'csv'])('authenticates %s downloads and preserves 401 status', async (format) => {
    setAccessTokenProvider(() => 'test-access-token')
    fetch.mockResolvedValue(new Response('{"detail":"A valid user access token is required."}', {
      status: 401, headers: { 'content-type': 'application/json' },
    }))
    await expect(api.downloadReport(7, format, 3)).rejects.toMatchObject({ status: 401, offline: false })
    expect(fetch).toHaveBeenCalledWith(api.reportUrl(7, format, 3), {
      headers: { Authorization: 'Bearer test-access-token' }, signal: expect.any(AbortSignal),
    })
  })

  it.each([null, ''])('does not send private requests when a configured session is missing (%s)', async (token) => {
    setAccessTokenProvider(() => token)
    await expect(api.listProducts()).rejects.toMatchObject({ status: 401, offline: false })
    await expect(api.downloadReport(7, 'csv')).rejects.toMatchObject({ status: 401, offline: false })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('does not misreport identity-provider failures as backend downtime', async () => {
    setAccessTokenProvider(() => Promise.reject(new Error('test provider unavailable')))
    await expect(api.listProducts()).rejects.toMatchObject({ status: 401, offline: false })
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('request isolation across account boundaries', () => {
  it('does not send a request if the account changes while obtaining its token', async () => {
    const pending = deferred()
    setAccessTokenProvider(() => pending.promise)
    const request = api.listProducts().catch((e) => e)
    setAccessTokenProvider(() => 'OFFLINE-TEST-bob')
    pending.resolve('OFFLINE-TEST-alice')
    expect((await request).name).toBe('AbortError')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('aborts requests and rejects stale data even if the transport ignores the abort', async () => {
    const pending = deferred()
    fetch.mockReturnValue(pending.promise)
    setAccessTokenProvider(() => 'OFFLINE-TEST-alice')
    const request = api.listProducts().catch((e) => e)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    const signal = fetch.mock.calls[0][1].signal
    invalidateAuthenticatedRequests()
    expect(signal.aborted).toBe(true)
    pending.resolve(new Response('[{"name":"Alice private product"}]', { headers: { 'content-type': 'application/json' } }))
    expect((await request).name).toBe('AbortError')
  })

  it('checks the account again after response-body parsing', async () => {
    const pending = deferred()
    const json = vi.fn(() => pending.promise)
    fetch.mockResolvedValue({ ok: true, status: 200, headers: new Headers({ 'content-type': 'application/json' }), json })
    setAccessTokenProvider(() => 'OFFLINE-TEST-alice')
    const request = api.getAnalysis(7).catch((e) => e)
    await vi.waitFor(() => expect(json).toHaveBeenCalled())
    invalidateAuthenticatedRequests()
    pending.resolve({ privateReview: 'Synthetic Alice data' })
    expect((await request).name).toBe('AbortError')
  })

  it.each(['pdf', 'csv'])('never triggers a stale %s file download after account switching', async (format) => {
    const pending = deferred()
    const blob = vi.fn(() => pending.promise)
    URL.createObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    fetch.mockResolvedValue({ ok: true, status: 200, headers: new Headers(), blob })
    setAccessTokenProvider(() => 'OFFLINE-TEST-alice')
    const request = api.downloadReport(7, format).catch((e) => e)
    await vi.waitFor(() => expect(blob).toHaveBeenCalled())
    invalidateAuthenticatedRequests()
    pending.resolve(new Blob(['Synthetic report']))
    expect((await request).name).toBe('AbortError')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    expect(click).not.toHaveBeenCalled()
  })

  it('does not let a stale 401 sign out the new account', async () => {
    const pending = deferred()
    fetch.mockReturnValue(pending.promise)
    const rejected = vi.fn()
    setAccessTokenProvider(() => 'OFFLINE-TEST-alice', { onUnauthorized: rejected })
    const request = api.listProducts().catch((e) => e)
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    setAccessTokenProvider(() => 'OFFLINE-TEST-bob', { onUnauthorized: rejected })
    pending.resolve(new Response('{"detail":"Expired"}', { status: 401, headers: { 'content-type': 'application/json' } }))
    expect((await request).name).toBe('AbortError')
    expect(rejected).not.toHaveBeenCalled()
  })

  it('reports a current rejected token to the session controller without replaying a mutation', async () => {
    const rejected = vi.fn()
    setAccessTokenProvider(() => 'OFFLINE-TEST-alice', { onUnauthorized: rejected })
    fetch.mockResolvedValue(new Response('{"detail":"Expired"}', { status: 401, headers: { 'content-type': 'application/json' } }))
    await expect(api.reanalyze(7)).rejects.toMatchObject({ status: 401 })
    expect(rejected).toHaveBeenCalledWith('OFFLINE-TEST-alice')
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})

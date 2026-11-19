import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import HostedApp from '../components/HostedApp'
import demo from '../demo/demoAnalysis.json'
import { api, setAccessTokenProvider } from '../lib/api'
import { deferred, fakeProvider, fakeSession } from './helpers/fakeIdentity'

const name = (user) => `${user === 'alice' ? 'Alice' : 'Bob'} synthetic phone`
const product = (user, id = 7) => ({ id, name: `${name(user)}${id === 8 ? ' two' : ''}`, source: 'upload',
  totalReviews: 6, positivePercent: 50, averageRating: 3, analyzedAt: '2026-01-01T00:00:00Z' })
const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const analysis = (user) => ({ ...demo, analysisId: 9, reviews: [], reviewsIncluded: false,
  product: { id: 7, name: name(user), source: 'upload', domain: 'product' } })
const report = (user, ext) => new Response(new Blob([`Synthetic ${user} report`]), {
  headers: { 'content-disposition': `attachment; filename="${user}-synthetic.${ext}"` },
})

function backend(overrides = {}) {
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    const path = url.replace(api.baseUrl, '').split('?')[0]
    const token = options.headers?.Authorization
    if (!token) throw new Error('Private UI sent a request without its access token')
    const user = token.includes('bob') ? 'bob' : 'alice'
    if (overrides[path]) return overrides[path](user, options, url)
    if (path === '/health') return json({ status: 'ok' })
    if (path === '/products') return json([product(user), product(user, 8)])
    if (path === '/products/7/analysis') return json(analysis(user))
    if (path === '/products/7/reviews') return json({ items: [], total: 0, offset: 0, limit: 20 })
    if (path === '/history') return json([9, 4].map((id) => ({ id, productId: 7, productName: name(user), totalReviews: 6, createdAt: '2026-01-01T00:00:00Z' })))
    if (path === '/ai/status') return json({ enabled: false })
    if (path.endsWith('/report.pdf')) return report(user, 'pdf')
    if (path.endsWith('/report.csv')) return report(user, 'csv')
    if (path === '/compare') return json({ detail: 'Synthetic comparison request received' }, 409)
    return json({ detail: 'No synthetic fixture for this route' }, 404)
  })
}
const nav = (label) => screen.getAllByRole('navigation', { name: 'Main' })[0].querySelector(`a[href="${label}"]`)
async function signedIn(provider = fakeProvider(fakeSession()), overrides) {
  backend(overrides)
  const view = render(<HostedApp provider={provider} />)
  await screen.findByRole('link', { name: name('alice') })
  return { provider, ...view }
}
function submit(email = 'alice@example.invalid', password = 'offline-test-password') {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: password } })
  fireEvent.submit(screen.getByLabelText('Email').closest('form'))
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
  URL.createObjectURL = vi.fn(() => 'blob:synthetic-report')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
})
afterEach(() => { cleanup(); setAccessTokenProvider(null); vi.unstubAllEnvs(); vi.restoreAllMocks() })

describe('hosted session gate and minimal UI', () => {
  it('shows invite-only sign-in without self-enrollment or email recovery controls', async () => {
    vi.stubEnv('VITE_PUBLIC_DEMO', 'true')
    const provider = { ...fakeProvider(), register: vi.fn(), requestPasswordReset: vi.fn(), updatePassword: vi.fn() }
    render(<HostedApp provider={provider} />)
    expect(await screen.findByText(/This showcase is invite-only/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Create an account' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Forgot password?' })).not.toBeInTheDocument()
  })

  it('does not pretend that a production identity provider is available', () => {
    vi.stubEnv('VITE_AUTH_MODE', 'hosted')
    globalThis.fetch = vi.fn()
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText(/No production identity provider is connected/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
    expect(screen.getByLabelText('Email')).toBeDisabled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('preserves the normal local app without installing or calling an identity provider', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'local')
    globalThis.fetch = vi.fn(() => Promise.resolve(json([])))
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sign out' })).not.toBeInTheDocument()
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith(`${api.baseUrl}/products`, {}))
  })

  it('does not render or request a private deep link before restoration finishes', async () => {
    window.history.replaceState(null, '', '/products/7?tab=reviews')
    const pending = deferred()
    const provider = fakeProvider()
    provider.getSession = () => pending.promise
    backend()
    render(<HostedApp provider={provider} />)
    expect(screen.getByRole('heading', { name: 'Checking your session' })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    await act(async () => pending.resolve(null))
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('submits an accessible sign-in form, clears the password and signs out without retaining private content', async () => {
    const pending = deferred()
    const provider = fakeProvider()
    provider.signIn = vi.fn(() => pending.promise)
    backend()
    render(<HostedApp provider={provider} />)
    await screen.findByRole('heading', { name: 'Sign in' })
    const email = screen.getByLabelText('Email'), password = screen.getByLabelText('Password')
    email.focus(); expect(document.activeElement).toBe(email)
    password.focus(); expect(document.activeElement).toBe(password)
    expect(email).toHaveAttribute('autocomplete', 'username')
    expect(password).toHaveAttribute('type', 'password')
    expect(password).toHaveAttribute('autocomplete', 'current-password')
    submit()
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Signing in…' })).toBeDisabled()
    expect(fetch).not.toHaveBeenCalled()
    await act(async () => pending.resolve(fakeSession()))
    await screen.findByRole('link', { name: name('alice') })
    expect(provider.signIn).toHaveBeenCalledWith({ email: 'alice@example.invalid', password: 'offline-test-password' })
    sessionStorage.setItem('reviews-dekho.pending-import', 'synthetic pending import')
    const out = screen.getByRole('button', { name: 'Sign out' })
    out.focus(); expect(document.activeElement).toBe(out)
    fireEvent.click(out)
    await screen.findByRole('button', { name: 'Sign in' })
    expect(screen.queryByText(name('alice'))).not.toBeInTheDocument()
    expect(JSON.stringify(localStorage)).not.toMatch(/offline-test-password|OFFLINE-TEST/)
    expect(JSON.stringify(sessionStorage)).not.toMatch(/offline-test-password|OFFLINE-TEST/)
    expect(sessionStorage.getItem('reviews-dekho.pending-import')).toBeNull()
  })

  it('shows a safe credential error and allows another sign-in attempt', async () => {
    backend()
    render(<HostedApp provider={fakeProvider()} />)
    await screen.findByRole('heading', { name: 'Sign in' })
    submit('alice@example.invalid', 'wrong-test-password')
    expect(await screen.findByRole('alert')).toHaveTextContent('Sign-in failed. Check your email and password, then try again.')
    expect(screen.getByLabelText('Password')).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
    submit()
    await screen.findByRole('link', { name: name('alice') })
  })

  it('does not expose provider internals when restoration fails', async () => {
    const provider = fakeProvider()
    provider.getSession = async () => { throw new Error('sensitive provider details') }
    backend()
    render(<HostedApp provider={provider} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Couldn’t restore your session. Sign in again.')
    expect(document.body.textContent).not.toContain('sensitive provider details')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('clears the workspace and shows a session error when the backend rejects the current token', async () => {
    backend({ '/products': () => json({ detail: 'Expired' }, 401) })
    render(<HostedApp provider={fakeProvider(fakeSession())} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/session expired.*Sign in again/)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
  })

  it('maintains one provider subscription under React StrictMode and cleans up on unmount', async () => {
    backend()
    const provider = fakeProvider(fakeSession())
    const view = render(<StrictMode><HostedApp provider={provider} /></StrictMode>)
    await screen.findByRole('link', { name: name('alice') })
    expect(provider.listenerCount()).toBe(1)
    view.unmount()
    expect(provider.listenerCount()).toBe(0)
  })

  it('restores an expired session through the provider before making any authenticated API request', async () => {
    const provider = fakeProvider(fakeSession('alice', { expiresAt: Date.now() - 1 }))
    const refresh = vi.spyOn(provider, 'refreshSession')
    backend()
    render(<HostedApp provider={provider} />)
    await screen.findByRole('link', { name: name('alice') })
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls.every(([, options]) => options.headers.Authorization === 'Bearer OFFLINE-TEST-alice-refreshed')).toBe(true)
  })

  it('hides private content when refresh is pending and clears it on failed refresh', async () => {
    let clock = Date.now()
    vi.spyOn(Date, 'now').mockImplementation(() => clock)
    const pending = deferred()
    const provider = fakeProvider(fakeSession())
    provider.refreshSession = () => pending.promise
    await signedIn(provider)
    clock += 60001
    fireEvent.click(nav('/history'))
    await screen.findByRole('heading', { name: 'Checking your session' })
    expect(screen.queryByText(name('alice'))).not.toBeInTheDocument()
    expect(screen.queryByText('Signed in as alice@example.invalid')).not.toBeInTheDocument()
    await act(async () => pending.reject(new Error('test refresh failed')))
    expect(await screen.findByRole('alert')).toHaveTextContent(/session expired.*Sign in again/)
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
  })
})

describe('private UI state is scoped to the current account', () => {
  it('clears products and rejects a stale product list even if abort is ignored', async () => {
    const pending = deferred()
    const provider = fakeProvider(fakeSession())
    backend({ '/products': (user) => user === 'alice' ? pending.promise : json([product(user)]) })
    render(<HostedApp provider={provider} />)
    await screen.findByText('Signed in as alice@example.invalid')
    await vi.waitFor(() => expect(fetch.mock.calls.some(([u]) => u.endsWith('/products'))).toBe(true))
    const oldSignal = fetch.mock.calls.find(([u]) => u.endsWith('/products'))[1].signal
    act(() => provider.change(fakeSession('bob')))
    await screen.findByRole('link', { name: name('bob') })
    expect(oldSignal.aborted).toBe(true)
    await act(async () => pending.resolve(json([product('alice')])))
    expect(screen.queryByText(name('alice'))).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('clears an analysis and selected product ID, and cannot reuse a late response for the same ID', async () => {
    const pending = deferred()
    const { provider } = await signedIn(undefined, { '/products/7/analysis': (user) => user === 'alice' ? pending.promise : json(analysis(user)) })
    fireEvent.click(screen.getByRole('link', { name: name('alice') }))
    await vi.waitFor(() => expect(fetch.mock.calls.some(([u]) => u.includes('/7/analysis'))).toBe(true))
    expect(window.location.pathname).toBe('/products/7')
    act(() => provider.change(fakeSession('bob')))
    await screen.findByRole('link', { name: name('bob') })
    expect(window.location.pathname).toBe('/')
    fireEvent.click(screen.getByRole('link', { name: name('bob') }))
    await screen.findByRole('heading', { name: name('bob') })
    await act(async () => pending.resolve(json(analysis('alice'))))
    expect(screen.queryByRole('heading', { name: name('alice') })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: name('bob') })).toBeInTheDocument()
  })

  it('clears product/run selections and pending report downloads on account switching', async () => {
    const pending = deferred()
    const { provider } = await signedIn(undefined, { '/products/7/report.pdf': () => pending.promise })
    fireEvent.click(nav('/reports'))
    await screen.findByRole('heading', { name: 'Reports' })
    await screen.findByRole('option', { name: name('alice') })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '7' } })
    fireEvent.change(await screen.findByLabelText('Analysis run'), { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    await screen.findByRole('button', { name: 'Preparing PDF…' })
    act(() => provider.change(fakeSession('bob')))
    await screen.findByRole('link', { name: name('bob') })
    expect(window.location.pathname).toBe('/')
    await act(async () => pending.resolve(report('alice', 'pdf')))
    expect(HTMLAnchorElement.prototype.click).not.toHaveBeenCalled()
    expect(URL.createObjectURL).not.toHaveBeenCalled()
    fireEvent.click(nav('/reports'))
    await screen.findByRole('option', { name: name('bob') })
    expect(screen.getByLabelText('Product')).toHaveValue('')
    expect(screen.queryByLabelText('Analysis run')).not.toBeInTheDocument()
    expect(screen.queryByText(/Downloaded alice/)).not.toBeInTheDocument()
  })

  it('clears completed download messages and revokes remaining blob URLs on sign-out', async () => {
    const { provider } = await signedIn()
    fireEvent.click(nav('/reports'))
    await screen.findByRole('option', { name: name('alice') })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '7' } })
    await screen.findByLabelText('Analysis run')
    fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    await screen.findByText('Downloaded alice-synthetic.csv')
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    expect(screen.queryByText('Downloaded alice-synthetic.csv')).not.toBeInTheDocument()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic-report')
    submit('bob@example.invalid')
    await screen.findByRole('link', { name: name('bob') })
    fireEvent.click(nav('/reports'))
    await screen.findByRole('option', { name: name('bob') })
    expect(screen.getByLabelText('Product')).toHaveValue('')
    expect(provider.listenerCount()).toBe(1)
  })

  it('clears comparison query parameters and prevents old browser history from restoring them for another account', async () => {
    const { provider } = await signedIn()
    fireEvent.click(nav('/compare'))
    await screen.findByLabelText('Product A')
    await within(screen.getByLabelText('Product A')).findByRole('option', { name: name('alice') })
    fireEvent.change(screen.getByLabelText('Product A'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Product B'), { target: { value: '8' } })
    fireEvent.change(await screen.findByLabelText('Run for side A'), { target: { value: '4' } })
    const previousUrl = window.location.pathname + window.location.search
    const previousState = window.history.state
    expect(previousUrl).toContain('ra=4')
    act(() => provider.change(fakeSession('bob')))
    await screen.findByRole('link', { name: name('bob') })
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toBe('')
    const from = fetch.mock.calls.length
    act(() => {
      window.history.pushState(previousState, '', previousUrl)
      window.dispatchEvent(new PopStateEvent('popstate', { state: previousState }))
    })
    await vi.waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(window.location.search).toBe('')
    expect(fetch.mock.calls.slice(from).some(([u]) => u.includes('/compare?'))).toBe(false)
    fireEvent.click(nav('/compare'))
    await screen.findByLabelText('Product A')
    expect(screen.getByLabelText('Product A')).toHaveValue('')
    expect(screen.getByLabelText('Product B')).toHaveValue('')
  })
})

describe('hosted upload recovery', () => {
  const limits = { maxRows: 10, maxReviewChars: 1000, maxUploadBytes: 1048576, maxRequestBytes: 1310720 }
  const preview = { columns: ['review'], detected: { text: 'review' }, rowCount: 1,
    sampleRows: [{ review: 'Great' }], warnings: [] }
  const slot = 'reviews-dekho.pending-import'

  async function openUpload() {
    fireEvent.click(nav('/upload'))
    await screen.findByText(/Up to 10 reviews.*1,000 characters/)
  }

  async function chooseFile() {
    fireEvent.change(screen.getByLabelText('Review file'), {
      target: { files: [new File(['review\nGreat'], 'sample.csv', { type: 'text/csv' })] },
    })
    return screen.findByRole('button', { name: /Import and analyse|Retry same import/ })
  }

  it('uses server limits and reconciles an uncertain import after reload without submitting again', async () => {
    let key
    const overrides = {
      '/uploads/limits': () => json(limits),
      '/uploads/preview': () => json(preview),
      '/uploads/import': (_user, options) => {
        key = options.headers['Idempotency-Key']
        return json({ detail: 'Gateway timeout' }, 504)
      },
    }
    const view = await signedIn(fakeProvider(fakeSession()), overrides)
    await openUpload()
    expect(screen.getByText(/CSV or Excel.*1.0 MB/)).toBeInTheDocument()
    const button = await chooseFile()
    fireEvent.submit(button.closest('form'))
    fireEvent.submit(button.closest('form'))
    await screen.findByText(/The import may have completed/)
    expect(fetch.mock.calls.filter(([url]) => url.endsWith('/uploads/import'))).toHaveLength(1)
    expect(JSON.parse(sessionStorage.getItem(slot)).key).toBe(key)
    expect(sessionStorage.getItem(slot)).not.toContain('sample.csv')

    view.unmount()
    const lookup = vi.fn(() => json(product('alice')))
    await signedIn(fakeProvider(fakeSession()), { ...overrides, [`/uploads/import-status/${key}`]: lookup })
    await openUpload()
    expect(screen.getByText(/select the original file/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Check import status' }))
    await vi.waitFor(() => expect(window.location.pathname).toBe('/products/7'))
    expect(lookup).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/uploads/import'))).toBe(false)
    expect(sessionStorage.getItem(slot)).toBeNull()
  })

  it('reuses the original key only on an explicit retry and clears the pending key on account change', async () => {
    const keys = []
    const provider = fakeProvider(fakeSession())
    await signedIn(provider, {
      '/uploads/limits': () => json(limits), '/uploads/preview': () => json(preview),
      '/uploads/import': (_user, options) => {
        keys.push(options.headers['Idempotency-Key'])
        return json({ detail: 'Unavailable' }, 503)
      },
    })
    await openUpload()
    fireEvent.click(await chooseFile())
    await screen.findByText(/The import may have completed/)
    fireEvent.click(screen.getByRole('button', { name: 'Retry same import' }))
    await screen.findByText(/The import may have completed/)
    expect(keys).toEqual([keys[0], keys[0]])
    await act(async () => provider.change(fakeSession('bob')))
    await screen.findByRole('link', { name: name('bob') })
    expect(sessionStorage.getItem(slot)).toBeNull()
    await openUpload()
    expect(screen.queryByRole('button', { name: 'Check import status' })).toBeNull()
  })
})

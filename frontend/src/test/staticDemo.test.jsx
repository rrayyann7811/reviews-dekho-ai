// The static, demo-only build (Phase 8): no network request at all, the demo product works, clear notices elsewhere.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/staticDemo', async () => ({ ...(await vi.importActual('../lib/staticDemo')), STATIC_DEMO: true }))
const { default: App } = await import('../App')
const { api, setAccessTokenProvider } = await import('../lib/api')

beforeEach(() => {
  localStorage.clear()
  globalThis.fetch = vi.fn(() => Promise.reject(new Error('the static demo must not make requests')))
})
afterEach(() => { window.location.hash = ''; vi.restoreAllMocks() })

function openAt(hash) {
  window.location.hash = hash
  return render(<App />)
}

describe('static demo build', () => {
  it('ignores hosted-auth configuration and never gates the synthetic demo behind sign-in', async () => {
    vi.stubEnv('VITE_AUTH_MODE', 'hosted')
    try {
      openAt('#/history')
      await screen.findByRole('heading', { name: 'Analysis history' })
      expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument()
      expect(fetch).not.toHaveBeenCalled()
    } finally { vi.unstubAllEnvs() }
  })

  it('never invokes an installed identity-provider hook', async () => {
    const provider = vi.fn(() => { throw new Error('identity provider must not run in the static demo') })
    setAccessTokenProvider(provider)
    await expect(api.listProducts()).rejects.toMatchObject({ offline: true })
    await expect(api.downloadReport(1, 'pdf')).rejects.toMatchObject({ offline: true })
    expect(provider).not.toHaveBeenCalled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('carries no API address and fails every API call before fetch', async () => {
    expect(api.baseUrl).toBe('')
    expect(api.reportUrl(7, 'pdf')).not.toMatch(/localhost|https?:/)
    await expect(api.health()).rejects.toMatchObject({ offline: true, message: expect.stringMatching(/online demo/) })
    await expect(api.listProducts()).rejects.toMatchObject({ offline: true })
    await expect(api.downloadReport(7, 'pdf')).rejects.toMatchObject({ offline: true })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows the demo product without contacting any server', async () => {
    openAt('#/products/demo')
    expect(await screen.findByRole('heading', { level: 1, name: /Kestrel Orbit 5G/ })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('explains what needs the local app instead of asking to start a server', async () => {
    openAt('#/upload')
    expect(await screen.findByText('Reading and analysing uploaded files isn’t available in the online demo')).toBeInTheDocument()
    expect(screen.getByText(/shows the interface with the built-in demo product, whose reviews are synthetic/)).toBeInTheDocument()
    expect(screen.queryByText('The analysis server isn’t running')).not.toBeInTheDocument()
    expect(screen.queryByText(/uvicorn/)).not.toBeInTheDocument()
    // The drop area is disabled: choosing a file can't start an upload.
    expect(screen.getByRole('button', { name: 'choose a file' })).toBeDisabled()
    expect(screen.getByLabelText('Review file')).toBeDisabled()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('settings say the server isn’t used', async () => {
    openAt('#/settings')
    expect(await screen.findByText(/Not used: this is the online demo/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})

// Phase 8 live-audit follow-up: no page may present a backend feature as working, or ask for a local server.
const LOCAL_SETUP = /isn’t running|Start it|uvicorn|backend folder|Server offline|Available when the server/

describe('static demo messaging', () => {
  it('Analyze page: explains the demo, disables collection and offers the demo product instead', async () => {
    openAt('#/analyze')
    expect(await screen.findByText('Collecting reviews from links isn’t available in the online demo')).toBeInTheDocument()
    expect(screen.getAllByText(/shows the interface with the built-in demo product/).length).toBeGreaterThan(0)
    const link = screen.getByLabelText('Product link')
    expect(link).toBeDisabled()
    expect(link).toHaveAccessibleDescription(/needs the full app running on your own computer/)
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeDisabled()
    expect(screen.getByRole('link', { name: 'Open the demo product' })).toHaveAttribute('href', '#/products/demo')
    // App Store collection is not presented as working; the demo store link is.
    expect(screen.getByText('Apple App Store')).toHaveTextContent(/^Apple App StoreSupported in the full app$/)
    expect(screen.getByText('Demo store')).toHaveTextContent(/^Demo storeOpens the demo product$/)
    expect(screen.queryByText(/^Supported$/)).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('a submitted link (e.g. by pressing Enter) never shows local-server instructions', async () => {
    openAt('#/analyze')
    const form = (await screen.findByLabelText('Product link')).closest('form')
    fireEvent.submit(form)
    const message = await screen.findByText('Not available in the online demo')
    expect(message.closest('[role="status"]')).toHaveTextContent(/needs the full app running on your own computer/)
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('Overview: the link form is disabled and the panels don’t promise live collection or upload', async () => {
    openAt('#/')
    expect(await screen.findByText(/This online demo opens the built-in demo product only/)).toBeInTheDocument()
    expect(screen.getByText('Available in the full app on your own computer.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeDisabled()
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
  })

  it('History: explains the demo instead of a server error, and still lists the demo product', async () => {
    openAt('#/history')
    expect(await screen.findByText('Showing the built-in demo product')).toBeInTheDocument()
    expect(screen.getByText(/Real analysis history is kept by the full app running on your own computer/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Kestrel Orbit 5G/ })).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('Sidebar: says "Online demo" in words, never "Server offline"', async () => {
    openAt('#/products/demo')
    await screen.findByRole('heading', { level: 1, name: /Kestrel Orbit 5G/ })
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0].parentElement
    expect(within(nav).getByText('Online demo')).toBeInTheDocument()
    expect(screen.queryByText('Server offline')).not.toBeInTheDocument()
  })

  it('Compare and Reports use demo wording', async () => {
    const { unmount } = openAt('#/compare')
    expect(await screen.findByText('Comparisons need the full app')).toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
    unmount()
    openAt('#/reports')
    await screen.findByText('Generating reports isn’t available in the online demo')
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'demo' } })
    expect(document.body.textContent).not.toMatch(LOCAL_SETUP)
    expect(fetch).not.toHaveBeenCalled()
  })

  it('no route makes a request', async () => {
    for (const route of ['#/', '#/analyze', '#/upload', '#/history', '#/products/demo', '#/products/demo?tab=reviews',
      '#/products/demo?tab=aspects', '#/compare', '#/reports', '#/settings', '#/nowhere']) {
      const { unmount } = openAt(route)
      await screen.findByRole('heading', { level: 1 })
      unmount()
    }
    expect(fetch).not.toHaveBeenCalled()
  })
})

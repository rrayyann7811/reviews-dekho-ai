// The normal (local) app keeps its own wording and controls: the static-demo changes apply to the demo build only.
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'

const json = (body) => Promise.resolve(new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } }))

function renderAt(path) {
  return render(
    <SettingsProvider><ServerStatusProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></ServerStatusProvider></SettingsProvider>,
  )
}
const sidebar = () => screen.getAllByRole('navigation', { name: 'Main' })[0].parentElement

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('normal app, backend not running', () => {
  beforeEach(() => { globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch'))) })

  it('the sidebar still reports the server as offline', async () => {
    renderAt('/settings')
    expect(await within(sidebar()).findByText('Server offline')).toBeInTheDocument()
    expect(screen.queryByText('Online demo')).not.toBeInTheDocument()
  })

  it('History keeps its local server warning', async () => {
    renderAt('/history')
    expect(await screen.findByText('The analysis server isn’t running, so saved analyses can’t be loaded.')).toBeInTheDocument()
    expect(screen.queryByText(/online demo/)).not.toBeInTheDocument()
  })

  it('Analyze stays enabled with its normal labels and no demo notice', async () => {
    renderAt('/analyze')
    expect(await screen.findByLabelText('Product link')).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Use the demo product link' })).toBeInTheDocument()
    expect(screen.getByText('Apple App Store')).toHaveTextContent(/^Apple App StoreSupported$/)
    expect(screen.queryByText(/online demo|in the full app/)).not.toBeInTheDocument()
  })

  it('Overview and Upload keep their normal wording and controls', async () => {
    const { unmount } = renderAt('/')
    expect(await screen.findByText(/Supported: Apple App Store apps and the demo store/)).toBeInTheDocument()
    expect(screen.getByText('Works with reviews from any website.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Analyze' })).toBeEnabled()
    unmount()
    renderAt('/upload')
    expect(await screen.findByRole('button', { name: 'choose a file' })).toBeEnabled()
    expect(screen.queryByText(/online demo/)).not.toBeInTheDocument()
  })
})

describe('normal app, backend running', () => {
  it('the sidebar reports the server as connected', async () => {
    globalThis.fetch = vi.fn((url) => json(String(url).endsWith('/health') ? { status: 'ok' } : []))
    renderAt('/settings')
    expect(await within(sidebar()).findByText('Server connected')).toBeInTheDocument()
  })
})

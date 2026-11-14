// The static, demo-only build (Phase 8): no network request at all, the demo product works, clear notices elsewhere.
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/staticDemo', async () => ({ ...(await vi.importActual('../lib/staticDemo')), STATIC_DEMO: true }))
const { default: App } = await import('../App')

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
  it('shows the demo product without contacting any server', async () => {
    openAt('#/products/demo')
    expect(await screen.findByRole('heading', { level: 1, name: /Kestrel Orbit 5G/ })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('explains what needs the local app instead of asking to start a server', async () => {
    openAt('#/upload')
    expect(await screen.findByText('Reading and analysing uploaded files isn’t available in the online demo')).toBeInTheDocument()
    expect(screen.getByText(/shows only the built-in demo product \(synthetic reviews\)/)).toBeInTheDocument()
    expect(screen.queryByText('The analysis server isn’t running')).not.toBeInTheDocument()
    expect(screen.queryByText(/uvicorn/)).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('settings say the server isn’t used', async () => {
    openAt('#/settings')
    expect(await screen.findByText(/Not used: this is the online demo/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Check again' })).not.toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
  })
})

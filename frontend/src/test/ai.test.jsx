// Phase 6b: the optional AI overview panel (API mocked).
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import demo from '../demo/demoAnalysis.json'
import { api } from '../lib/api'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'

const json = (body, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const ANALYSIS = { ...demo, analysisId: 9, reviews: [], reviewsIncluded: false,
  product: { id: 7, name: 'Stored Phone', source: 'upload', domain: 'product' } }
const ON = { enabled: true, available: true, model: 'llama3.2:3b', reason: null }
const ACCEPTED = {
  id: 1, analysisId: 9, model: 'llama3.2:3b', status: 'accepted', attempts: 1, problems: [],
  sentences: [{ text: 'Reviewers in this sample praise the Battery.', claims: ['C1'], excerpts: ['E1'] }],
  references: { O: 'Overall figures', C1: 'Battery', E1: 'R-1053' },
  label: 'AI-written by llama3.2:3b, running locally through Ollama, from the evidence-backed summary. Checked automatically, which catches some errors but not all.',
}

function mockBackend(routes) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const [path] = url.replace(api.baseUrl, '').split('?')
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (handler === undefined) return json({ detail: 'This address doesn’t exist on the API.' }, 404)
    return typeof handler === 'function' ? handler(init) : json(handler)
  })
}
const renderAt = (path) => render(
  <SettingsProvider><ServerStatusProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></ServerStatusProvider></SettingsProvider>)
const base = { 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS }

beforeEach(() => localStorage.clear())

describe('AI overview', () => {
  it('is not shown when turned off', async () => {
    mockBackend({ ...base, 'GET /ai/status': { ...ON, enabled: false, available: false } })
    renderAt('/products/7')
    await screen.findByText('Summary')
    await vi.waitFor(() => expect(fetch.mock.calls.some(([u]) => u.endsWith('/ai/status'))).toBe(true))
    expect(screen.queryByText(/AI-written overview/)).not.toBeInTheDocument()
  })

  it('explains when the local model isn’t available', async () => {
    mockBackend({ ...base, 'GET /ai/status': { ...ON, available: false, reason: 'The local Ollama server isn’t running (start it with “ollama serve”).' },
      'GET /products/7/ai-summary': null })
    renderAt('/products/7')
    expect(await screen.findByText(/The local Ollama server isn’t running/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Write an AI overview/ })).not.toBeInTheDocument()
  })

  it('writes an overview on request and shows it below — not instead of — the summary', async () => {
    let finish
    mockBackend({ ...base, 'GET /ai/status': ON, 'GET /products/7/ai-summary': null,
      'GET /products/7/reviews/R-1053': demo.reviews.find((r) => r.id === 'R-1053') ?? demo.reviews[0],
      'POST /products/7/ai-summary': () => new Promise((resolve) => { finish = () => resolve(json(ACCEPTED)) }) })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: /Write an AI overview/ }))
    expect(await screen.findByText(/The local model is writing/)).toBeInTheDocument()
    finish()
    const sentence = await screen.findByText(/Reviewers in this sample praise the Battery\./)
    expect(within(sentence).getByText('Battery')).toBeInTheDocument()          // claim chip
    expect(screen.getByText(/Checked automatically, which catches some errors but not all/)).toBeInTheDocument()
    expect(screen.getByText(demo.summary.overview)).toBeInTheDocument()      // the evidence-backed summary is still there
    fireEvent.click(within(sentence).getByRole('button', { name: 'Review R-1053' }))
    expect(await screen.findByRole('region', { name: 'Selected review' })).toBeInTheDocument()
  })

  it('a rejected attempt shows why, and no AI text', async () => {
    mockBackend({ ...base, 'GET /ai/status': ON, 'GET /products/7/ai-summary': {
      ...ACCEPTED, status: 'rejected', attempts: 2, sentences: [],
      problems: ['Sentence 1 uses numbers that aren’t in the cited evidence: 99.'] } })
    renderAt('/products/7')
    expect(await screen.findByText('The AI text didn’t pass the checks, so it isn’t shown')).toBeInTheDocument()
    expect(screen.getByText(/numbers that aren’t in the cited evidence: 99/)).toBeInTheDocument()
    expect(screen.queryByText(/AI-written by/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Write again/ })).toBeInTheDocument()
  })

  it('shows the server’s reason when writing fails', async () => {
    mockBackend({ ...base, 'GET /ai/status': ON, 'GET /products/7/ai-summary': null,
      'POST /products/7/ai-summary': () => json({ detail: 'The local model took too long to answer.' }, 504) })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: /Write an AI overview/ }))
    expect(await screen.findByText('The local model took too long to answer.')).toBeInTheDocument()
  })

  it('is not offered for the demo product', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/products/demo')
    await screen.findByText('Summary')
    expect(screen.queryByText(/AI-written overview/)).not.toBeInTheDocument()
  })
})

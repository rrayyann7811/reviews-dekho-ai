// Phase 6a: report downloads and the evidence-backed summary in the UI.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import demo from '../demo/demoAnalysis.json'
import { api } from '../lib/api'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'

const json = (body, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const pdf = (name) => Promise.resolve(new Response(new Blob(['%PDF-1.4']), {
  headers: { 'content-type': 'application/pdf', 'content-disposition': `attachment; filename="${name}"` } }))

const PRODUCT = { id: 7, name: 'Stored Phone', brand: null, category: null, source: 'upload', totalReviews: 63,
  averageRating: 3.6, positivePercent: 60, analyzedAt: '2026-11-14T10:00:00Z' }
const RUNS = [
  { id: 9, productId: 7, productName: 'Stored Phone', createdAt: '2026-11-14T10:00:00Z', totalReviews: 64 },
  { id: 4, productId: 7, productName: 'Stored Phone', createdAt: '2026-11-10T10:00:00Z', totalReviews: 63 },
]
const ANALYSIS = { ...demo, analysisId: 9, reviews: [], reviewsIncluded: false,
  product: { id: 7, name: 'Stored Phone', source: 'upload', domain: 'product' } }

function mockBackend(routes) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const [path, query = ''] = url.replace(api.baseUrl, '').split('?')
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (handler === undefined) return json({ detail: 'This address doesn’t exist on the API.' }, 404)
    return typeof handler === 'function' ? handler(init, new URLSearchParams(query)) : json(handler)
  })
}

function renderAt(path) {
  return render(
    <SettingsProvider><ServerStatusProvider><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></ServerStatusProvider></SettingsProvider>,
  )
}

let clicked
beforeEach(() => {
  localStorage.clear()
  clicked = []
  URL.createObjectURL = vi.fn(() => 'blob:report')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function click() { clicked.push(this.download) })
})
afterEach(() => vi.restoreAllMocks())

const calls = (part) => fetch.mock.calls.map(([u]) => u).filter((u) => u.includes(part))

describe('Reports page', () => {
  it('downloads the PDF of the latest run, then of a chosen earlier run', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products': [PRODUCT], 'GET /history': RUNS,
      'GET /products/7/report.pdf': (_i, params) => pdf(`reviews-dekho-stored-phone-run-${params.get('analysis_id') ?? 9}.pdf`) })
    renderAt('/reports')
    await screen.findByRole('option', { name: 'Stored Phone' })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '7' } })
    const runSelect = await screen.findByLabelText('Analysis run')
    expect(within(runSelect).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Latest #9 · 14 Nov 2026 · 64 reviews', 'Run #4 · 10 Nov 2026 · 63 reviews'])
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(await screen.findByText('Downloaded reviews-dekho-stored-phone-run-9.pdf')).toBeInTheDocument()
    expect(calls('/report.pdf').at(-1)).toBe(`${api.baseUrl}/products/7/report.pdf`)

    fireEvent.change(runSelect, { target: { value: '4' } })
    fireEvent.click(screen.getByRole('button', { name: 'Download PDF' }))
    expect(await screen.findByText('Downloaded reviews-dekho-stored-phone-run-4.pdf')).toBeInTheDocument()
    expect(calls('/report.pdf').at(-1)).toBe(`${api.baseUrl}/products/7/report.pdf?analysis_id=4`)
    expect(clicked).toEqual(['reviews-dekho-stored-phone-run-9.pdf', 'reviews-dekho-stored-phone-run-4.pdf'])
  })

  it('shows progress, then the server’s reason when a download fails', async () => {
    let finish
    mockBackend({ 'GET /health': {}, 'GET /products': [PRODUCT], 'GET /history': RUNS,
      'GET /products/7/report.csv': () => new Promise((resolve) => { finish = () => resolve(json({ detail: 'This analysis was made by an older version of the app.' }, 409)) }) })
    renderAt('/reports')
    await screen.findByRole('option', { name: 'Stored Phone' })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '7' } })
    await screen.findByLabelText('Analysis run')
    fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
    expect(await screen.findByRole('button', { name: 'Preparing CSV…' })).toBeDisabled()
    finish()
    expect(await screen.findByRole('alert')).toHaveTextContent('This analysis was made by an older version of the app.')
    expect(clicked).toEqual([])
  })

  it('explains when a product has no analysis yet', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products': [PRODUCT], 'GET /history': [] })
    renderAt('/reports')
    await screen.findByRole('option', { name: 'Stored Phone' })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: '7' } })
    expect(await screen.findAllByText('This product hasn’t been analysed yet.')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: /Download/ })).not.toBeInTheDocument()
  })

  it('needs the server', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/reports')
    expect(await screen.findAllByText('Available when the server is running.')).toHaveLength(2)
  })
})

describe('analysis page', () => {
  it('downloads the PDF of the run being viewed', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS,
      'GET /products/7/report.pdf': () => pdf('reviews-dekho-stored-phone-run-9.pdf') })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Download PDF' }))
    expect(await screen.findByText('Downloaded reviews-dekho-stored-phone-run-9.pdf')).toBeInTheDocument()
    expect(calls('/report.pdf')).toEqual([`${api.baseUrl}/products/7/report.pdf?analysis_id=9`])
  })

  it('the demo product explains that it has no reports', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/products/demo')
    expect(await screen.findByText(/Reports can’t be downloaded for the demo product/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Download PDF' })).not.toBeInTheDocument()
  })
})

describe('evidence-backed summary', () => {
  it('shows each claim’s counts and up to three exact excerpts', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS })
    renderAt('/products/7')
    const claim = demo.summary.strengths[0]
    const block = (await screen.findByText(claim.aspect, { selector: 'p' })).closest('li')
    expect(within(block).getByText(`${claim.count} of ${claim.mentions} reviews that mention it are positive (${claim.percent}%)`)).toBeInTheDocument()
    const quotes = within(block).getAllByRole('button', { name: 'Read review' })
    expect(quotes).toHaveLength(claim.evidence.length)
    for (const excerpt of claim.evidence) expect(within(block).getByText(`“${excerpt.text}”`, { exact: false })).toBeInTheDocument()
  })

  it('still shows version 1 summaries (one example, no evidence list)', async () => {
    const v1 = { ...ANALYSIS, summary: { overview: 'Old overview.', notes: [], mixed: [], complaints: [],
      strengths: [{ aspect: 'Battery', mentions: 4, count: 3, percent: 75, positive: 3, neutral: 1, negative: 0,
        example: { reviewId: 'R-1', text: 'Great battery' } }] } }
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': v1 })
    renderAt('/products/7')
    const block = (await screen.findByText('Battery', { selector: 'p' })).closest('li')
    expect(within(block).getByText('“Great battery”', { exact: false })).toBeInTheDocument()
    expect(within(block).getAllByRole('button', { name: 'Read review' })).toHaveLength(1)
  })
})

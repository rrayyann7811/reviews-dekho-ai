// Phase 7: side-by-side comparison. The fixture is a real /api/compare response (backend/scripts/make_compare_fixture.py),
// checked against the live API by backend/tests/test_frontend_contract.py.
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import { api } from '../lib/api'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'
import fixture from './fixtures/comparison.json'

const json = (body, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))
const copy = () => structuredClone(fixture)

const PRODUCTS = [
  { id: 1, name: 'Alpha Phone', source: 'upload', totalReviews: 70, analyzedAt: '2026-11-14T10:00:00Z' },
  { id: 2, name: 'Beta Phone', source: 'upload', totalReviews: 330, analyzedAt: '2026-11-14T10:00:00Z' },
  { id: 3, name: 'Fresh Phone', source: 'manual', totalReviews: 0, analyzedAt: null },
]
const RUNS = {
  1: [{ id: 5, productId: 1, createdAt: '2026-11-14T10:00:00Z', totalReviews: 70 },
      { id: 3, productId: 1, createdAt: '2026-11-12T10:00:00Z', totalReviews: 60 }],
  2: [{ id: 6, productId: 2, createdAt: '2026-11-14T10:00:00Z', totalReviews: 330 }],
}

function mockBackend(routes) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const [path, query = ''] = url.replace(api.baseUrl, '').split('?')
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (handler === undefined) return json({ detail: 'This address doesn’t exist on the API.' }, 404)
    return typeof handler === 'function' ? handler(new URLSearchParams(query)) : json(handler)
  })
}
const standard = (compare = () => json(fixture)) => ({
  'GET /health': {}, 'GET /products': PRODUCTS, 'GET /compare': compare,
  'GET /history': (q) => json(RUNS[q.get('product_id')] ?? []),
})

function Location() {
  return <output data-testid="location">{useLocation().search}</output>
}

function renderAt(path) {
  return render(
    <SettingsProvider><ServerStatusProvider><MemoryRouter initialEntries={[path]}>
      <AppRoutes /><Location />
    </MemoryRouter></ServerStatusProvider></SettingsProvider>,
  )
}
const location = () => screen.getByTestId('location').textContent
const compareCalls = () => fetch.mock.calls.map(([u]) => u).filter((u) => u.includes('/compare?'))

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('Compare page: choosing what to compare', () => {
  it('picks two products and runs, keeps them in the URL, and asks the API for exactly that', async () => {
    mockBackend(standard())
    renderAt('/compare')
    const productA = await screen.findByLabelText('Product A')
    const options = within(productA).getAllByRole('option').map((o) => o.textContent)
    expect(options).toEqual(['Choose a product…', 'Alpha Phone', 'Beta Phone', 'Fresh Phone (not analysed yet)'])
    expect(options.join()).not.toMatch(/demo/i)                       // the in-browser demo can't be compared
    expect(within(productA).getByRole('option', { name: /Fresh Phone/ })).toBeDisabled()

    fireEvent.change(productA, { target: { value: '1' } })
    expect(location()).toBe('?a=1')
    fireEvent.change(screen.getByLabelText('Product B'), { target: { value: '2' } })
    expect(location()).toBe('?a=1&b=2')
    await screen.findByRole('region', { name: 'Side A: Alpha Phone' })
    expect(compareCalls().at(-1)).toBe(`${api.baseUrl}/compare?product_a=1&product_b=2`)

    const runA = await screen.findByLabelText('Run for side A')
    expect(within(runA).getAllByRole('option').map((o) => o.textContent))
      .toEqual(['Latest #5 · 14 Nov 2026 · 70 reviews', 'Run #3 · 12 Nov 2026 · 60 reviews'])
    fireEvent.change(runA, { target: { value: '3' } })
    expect(location()).toBe('?a=1&b=2&ra=3')
    await screen.findByRole('region', { name: 'Side A: Alpha Phone' })
    expect(compareCalls().at(-1)).toBe(`${api.baseUrl}/compare?product_a=1&product_b=2&analysis_a=3`)

    // Changing the product resets that side's run to "latest".
    fireEvent.change(productA, { target: { value: '2' } })
    expect(location()).toBe('?a=2&b=2')
  })

  it('opens a shared link with its runs selected', async () => {
    mockBackend(standard())
    renderAt('/compare?a=1&ra=3&b=2')
    await screen.findByRole('region', { name: 'Side B: Beta Phone' })
    expect(screen.getByLabelText('Product A')).toHaveValue('1')
    expect(await screen.findByLabelText('Run for side A')).toHaveValue('3')
    expect(compareCalls()[0]).toBe(`${api.baseUrl}/compare?product_a=1&product_b=2&analysis_a=3`)
  })

  it('allows the same product on both sides (two runs) and explains a same-run choice', async () => {
    const same = { ...copy(), sameProduct: true, sameRun: true,
      caveats: [{ code: 'same-run', severity: 'info', message: 'Both sides are the same analysis run, so every figure is identical.' }],
      statements: ['Both sides are the same analysis run, so there are no differences to describe.'] }
    mockBackend(standard(() => json(same)))
    renderAt('/compare?a=1&b=1')
    expect(await screen.findByText('Both sides are the same analysis run, so every figure is identical.')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Tone of the reviews' })).not.toBeInTheDocument()
  })
})

describe('Compare page: the comparison', () => {
  it('shows both sides, every figure as text, and the statements', async () => {
    mockBackend(standard())
    renderAt('/compare?a=1&b=2')
    const sideB = await screen.findByRole('region', { name: 'Side B: Beta Phone' })
    expect(within(sideB).getByText('290')).toBeInTheDocument()
    expect(within(sideB).getByText(/of 330/)).toBeInTheDocument()
    expect(within(sideB).getByText('(40 not in English)')).toBeInTheDocument()
    expect(within(sideB).getByText(/latest run/)).toBeInTheDocument()

    // Sentiment: percentages, counts and intervals are visible text, not only bar lengths or colours.
    const tone = screen.getByRole('heading', { name: 'Tone of the reviews' }).closest('section')
    const { a, b } = fixture.sentiment.negative
    expect(within(tone).getByRole('img', { name: `Negative, side A: ${a.percent}%, ${a.count} of ${a.n}, 95% interval ${a.interval[0]}%–${a.interval[1]}%` })).toBeInTheDocument()
    expect(within(tone).getByText(`${b.percent}%`)).toBeInTheDocument()
    expect(within(tone).getAllByText('Clear separation in these samples').length).toBeGreaterThan(0)
    expect(within(tone).getAllByText('Intervals overlap').length).toBeGreaterThan(0)
    expect(within(tone).getByText(/A is 23\.8 percentage points lower than B/)).toBeInTheDocument()

    // Star ratings as shares of rated reviews, with counts.
    const ratings = screen.getByRole('heading', { name: 'Star ratings' }).closest('section')
    expect(within(within(ratings).getByRole('list', { name: 'Star ratings, side B' })).getAllByRole('listitem')).toHaveLength(5)
    expect(within(ratings).getByText('from 330 rated reviews')).toBeInTheDocument()

    // Statements are the server's, word for word; nothing claims a winner or significance.
    const statements = screen.getByRole('heading', { name: 'What the figures show' }).closest('section')
    for (const s of fixture.statements) expect(within(statements).getByText(s)).toBeInTheDocument()
    expect(statements.textContent).not.toMatch(/significan|winner|better|worse/i)
    expect(statements.textContent).toMatch(/neither side is a random or representative sample/)
  })

  it('shows every feature status in words, and never treats a missing feature as negative', async () => {
    const data = copy()
    data.features.push({ aspect: 'Refunds', comparable: false, mentionRate: null, tone: null,
      a: { status: 'not-looked-for', mentions: 0, positive: 0, neutral: 0, negative: 0, verdict: null, mentionRate: null },
      b: { status: 'unknown', mentions: 0, positive: 0, neutral: 0, negative: 0, verdict: null, mentionRate: null } })
    mockBackend(standard(() => json(data)))
    renderAt('/compare?a=1&b=2')
    await screen.findByRole('region', { name: 'Side A: Alpha Phone' })
    const cards = screen.getByRole('list', { name: 'Feature comparison' })
    const card = (name) => within(cards).getByRole('heading', { name }).closest('li')

    expect(within(card('Battery')).getByRole('img', { name: 'Battery, side A: 35 positive, 0 neutral, 0 negative mentions' })).toBeInTheDocument()
    expect(within(card('Battery')).getAllByText('Clear separation in these samples')).toHaveLength(2)
    expect(within(card('Packaging')).getByText('Looked for, not mentioned')).toBeInTheDocument()
    expect(within(card('Packaging')).getByText('Not compared: needs at least 3 mentions on both sides.')).toBeInTheDocument()
    const refunds = card('Refunds')
    expect(within(refunds).getByText('Not looked for')).toBeInTheDocument()
    expect(within(refunds).getByText('Unknown (older run)')).toBeInTheDocument()
    expect(within(refunds).getByText('Not compared: this feature wasn’t looked for on one side.')).toBeInTheDocument()
    expect(within(refunds).queryByText(/Negative|0%/)).not.toBeInTheDocument()

    // Each status that appears is explained once, above the features, not in every cell.
    const panel = screen.getByRole('heading', { name: 'Features' }).closest('section')
    expect(within(panel).getAllByText(/missing information, not a zero/)).toHaveLength(1)
    expect(within(panel).getByText('Looked for, and no analysed review mentioned it.')).toBeInTheDocument()
    expect(within(panel).queryByText(/Fewer than 3 mentions/)).not.toBeInTheDocument()   // no few-mention row here
  })

  it('says why nothing is compared when the sides share no features', async () => {
    const data = copy()
    data.features = [
      { aspect: 'Battery', comparable: false, mentionRate: null, tone: null,
        a: { ...data.features[0].a }, b: { status: 'not-looked-for', mentions: 0, positive: 0, neutral: 0, negative: 0, verdict: null, mentionRate: null } },
      { aspect: 'Login & account', comparable: false, mentionRate: null, tone: null,
        a: { status: 'not-looked-for', mentions: 0, positive: 0, neutral: 0, negative: 0, verdict: null, mentionRate: null }, b: { ...data.features[0].b } },
    ]
    mockBackend(standard(() => json(data)))
    renderAt('/compare?a=1&b=2')
    expect(await screen.findByText(/weren’t checked for any of the same features/)).toBeInTheDocument()
    expect(screen.queryByText(/needs at least 3 mentions on both sides/)).not.toBeInTheDocument()
  })

  it('has a table for wide screens and cards for narrow ones', async () => {
    mockBackend(standard())
    renderAt('/compare?a=1&b=2')
    await screen.findByRole('region', { name: 'Side A: Alpha Phone' })
    const table = screen.getByRole('table', { name: 'Feature comparison between side A and side B' })
    expect(table.parentElement).toHaveClass('hidden', 'lg:block')
    expect(screen.getByRole('list', { name: 'Feature comparison' })).toHaveClass('lg:hidden')
    expect(within(table).getAllByRole('rowheader').map((r) => r.textContent)).toEqual(fixture.features.map((f) => f.aspect))
  })
})

describe('Compare page: caveats and edge states', () => {
  it('lists warnings before notes, labelled for screen readers', async () => {
    const data = copy()
    data.caveats = [
      { code: 'app-store-recent', severity: 'info', message: 'App Store data covers only the most recent reviews.' },
      { code: 'size-gap', severity: 'warning', message: 'The samples differ a lot in size.' },
    ]
    mockBackend(standard(() => json(data)))
    renderAt('/compare?a=1&b=2')
    const heading = await screen.findByRole('heading', { name: /Read before comparing/ })
    expect(heading).toHaveTextContent('Read before comparing · 1 warning')
    const notices = within(heading.closest('section')).getAllByRole('status').map((n) => n.textContent)
    expect(notices).toEqual(['Warning: The samples differ a lot in size.', 'Note: App Store data covers only the most recent reviews.'])
  })

  it('shows "not measurable", never 0%, when a side has no analysed reviews', async () => {
    const data = copy()
    data.b.counts = { total: 12, analysed: 0, notAnalysed: 12, notAnalysedReasons: { languageNotSupported: 12 }, rated: 12 }
    data.b.sentiment = null
    data.sentiment = null
    mockBackend(standard(() => json(data)))
    renderAt('/compare?a=1&b=2')
    const tone = (await screen.findByRole('heading', { name: 'Tone of the reviews' })).closest('section')
    expect(within(tone).getAllByText('Not measurable: none of its reviews could be analysed.')).toHaveLength(3)
    expect(within(tone).getAllByText('Not measurable')).toHaveLength(3)
    expect(within(tone).queryByText('0%')).not.toBeInTheDocument()
  })

  it('handles missing star ratings', async () => {
    const data = copy()
    data.a.ratings = { ...data.a.ratings, rated: 0, average: null,
      distribution: data.a.ratings.distribution.map((r) => ({ ...r, count: 0, percent: null })) }
    data.a.counts.rated = 0
    mockBackend(standard(() => json(data)))
    renderAt('/compare?a=1&b=2')
    expect(await screen.findByText('No star ratings in this run.')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Side A: Alpha Phone' })).getByText('None')).toBeInTheDocument()
  })

  it('shows the server’s reason and can try again', async () => {
    let fail = true
    mockBackend(standard(() => (fail ? json({ detail: 'Analysis 6 doesn’t belong to this product.' }, 404) : json(fixture))))
    renderAt('/compare?a=1&ra=6&b=2')
    expect(await screen.findByText('Analysis 6 doesn’t belong to this product.')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByRole('region', { name: 'Side A: Alpha Phone' })).toBeInTheDocument()
  })

  it('explains when nothing has been analysed yet', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products': [PRODUCTS[2]] })
    renderAt('/compare')
    const empty = (await screen.findByText('No analysed products yet')).parentElement
    expect(within(empty).getByRole('link', { name: 'Upload reviews' })).toHaveAttribute('href', '/upload')
  })

  it('suggests comparing two runs when only one product is analysed', async () => {
    mockBackend({ ...standard(), 'GET /products': [PRODUCTS[0]] })
    renderAt('/compare')
    expect(await screen.findByText(/choose it on both sides and pick an earlier run/)).toBeInTheDocument()
  })

  it('explains that comparing needs the server when it is offline', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/compare?a=1&b=2')
    expect(await screen.findByText('Comparing needs the analysis server')).toBeInTheDocument()
    expect(screen.getByText('The analysis server isn’t running')).toBeInTheDocument()
    expect(compareCalls()).toEqual([])
  })
})

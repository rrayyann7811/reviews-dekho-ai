// Phase 5: the analysis dashboard reads stored results from the API (fetch is mocked with the API's shapes).
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import demo from '../demo/demoAnalysis.json'
import { api } from '../lib/api'
import { DEFAULT_FILTERS, filterReviews } from '../lib/reviewFilters'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'
import cases from './fixtures/review-query-cases.json'

const json = (body, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))

// What GET /products/7/analysis?include_reviews=false returns: everything except the reviews themselves.
const REVIEWS = demo.reviews
const ANALYSIS = {
  ...demo, analysisId: 3, reviews: [], reviewsIncluded: false,
  product: { id: 7, name: 'Stored Phone', brand: null, category: null, source: 'upload', domain: 'product' },
  ingestion: { ...demo.ingestion, fileName: 'phone.csv' },
}

function deferred() {
  let resolve
  const promise = new Promise((r) => { resolve = r })
  return { promise, resolve }
}

function mockBackend(routes) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const [path, query = ''] = url.replace(api.baseUrl, '').split('?')
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (handler === undefined) return json({ detail: 'This address doesn’t exist on the API.' }, 404)
    return typeof handler === 'function' ? handler(init, new URLSearchParams(query)) : json(handler)
  })
}

function serveReviews(reviews = REVIEWS, mismatches = ANALYSIS.stats.ratingSentimentMismatches) {
  return (_init, params) => {
    const all = filterReviews(reviews, { query: params.get('search') ?? '', sentiment: params.get('sentiment') ?? 'all',
      rating: params.get('rating') ?? 'all', sort: params.get('sort') ?? 'newest' }, mismatches)
    const offset = Number(params.get('offset'))
    const limit = Number(params.get('limit'))
    return json({ analysisId: 3, total: all.length, offset, limit, items: all.slice(offset, offset + limit) })
  }
}

const reviewCalls = () => fetch.mock.calls.map(([url]) => url).filter((u) => u.includes('/products/7/reviews?'))
  .map((u) => new URLSearchParams(u.split('?')[1]))

function renderAt(path) {
  return render(
    <SettingsProvider>
      <ServerStatusProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ServerStatusProvider>
    </SettingsProvider>,
  )
}

beforeEach(() => localStorage.clear())

describe('review filtering rules', () => {
  it.each(cases.cases)('matches the server for %j', ({ filters, expected }) => {
    const result = filterReviews(cases.reviews, { ...DEFAULT_FILTERS, ...filters }, cases.mismatchIds)
    expect(result.map((r) => r.id)).toEqual(expected)
  })
})

describe('reviews come from the server, a page at a time', () => {
  const routes = (extra = {}) => ({ 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS,
    'GET /products/7/reviews': serveReviews(), ...extra })

  it('loads 20 reviews, then the next 20, from the run being viewed', async () => {
    mockBackend(routes())
    renderAt('/products/7?tab=reviews')
    const total = REVIEWS.length
    expect(await screen.findByText(`Showing 20 of ${total} matching reviews (${total} total)`)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Show 20 more' }))
    expect(await screen.findByText(`Showing 40 of ${total} matching reviews (${total} total)`)).toBeInTheDocument()
    const [first, second] = reviewCalls()
    expect(Object.fromEntries(first)).toMatchObject({ offset: '0', limit: '20', analysis_id: '3', sort: 'newest', sentiment: 'all' })
    expect(second.get('offset')).toBe('20')
    // The analysis itself was loaded without the reviews.
    expect(fetch.mock.calls.some(([u]) => u.endsWith('/products/7/analysis?include_reviews=false'))).toBe(true)
  })

  it('filters, sorting and search are sent to the server and restart at the first page', async () => {
    mockBackend(routes())
    renderAt('/products/7?tab=reviews')
    await screen.findByText(/Showing 20 of/)
    fireEvent.change(screen.getByLabelText('Filter by sentiment'), { target: { value: 'negative' } })
    fireEvent.change(screen.getByLabelText('Filter by star rating'), { target: { value: '1' } })
    fireEvent.change(screen.getByLabelText('Sort reviews'), { target: { value: 'oldest' } })
    const expected = filterReviews(REVIEWS, { ...DEFAULT_FILTERS, sentiment: 'negative', rating: '1', sort: 'oldest' }, [])
    expect(await screen.findByText(`Showing ${expected.length} of ${expected.length} matching reviews (${REVIEWS.length} total)`)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search reviews'), { target: { value: 'zzzz-no-match' } })
    expect(await screen.findByText('No reviews match these filters')).toBeInTheDocument()
    const last = reviewCalls().at(-1)
    expect(Object.fromEntries(last)).toMatchObject({ sentiment: 'negative', rating: '1', sort: 'oldest', search: 'zzzz-no-match', offset: '0' })
  })

  it('shows an error with a retry when reviews can’t be loaded', async () => {
    let fail = true
    mockBackend(routes({ 'GET /products/7/reviews': (init, params) => (fail ? json({ detail: 'Database is busy.' }, 500) : serveReviews()(init, params)) }))
    renderAt('/products/7?tab=reviews')
    expect(await screen.findByText('Couldn’t load reviews')).toBeInTheDocument()
    expect(screen.getByText('Database is busy.')).toBeInTheDocument()
    fail = false
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText(/Showing 20 of/)).toBeInTheDocument()
  })

  it('“Read review” fetches that review and pins it above the list', async () => {
    const example = ANALYSIS.aspects.find((a) => a.examplePositive).examplePositive
    const review = REVIEWS.find((r) => r.id === example.reviewId)
    mockBackend(routes({ [`GET /products/7/reviews/${example.reviewId}`]: review }))
    renderAt('/products/7?tab=aspects')
    fireEvent.click((await screen.findAllByRole('button', { name: /Examples/ }))[0])
    fireEvent.click(screen.getAllByRole('button', { name: 'Read review' })[0])
    const pinned = await screen.findByRole('region', { name: 'Selected review' })
    expect(await within(pinned).findByText(review.text)).toBeInTheDocument()
    expect(fetch.mock.calls.some(([u]) => u.endsWith(`/reviews/${example.reviewId}?analysis_id=3`))).toBe(true)
    fireEvent.click(within(pinned).getByRole('button', { name: /Back to all reviews/ }))
    expect(screen.queryByRole('region', { name: 'Selected review' })).not.toBeInTheDocument()
  })

  it('the demo product still filters locally, without the server', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/products/demo?tab=reviews')
    expect(await screen.findByText(`Showing 20 of ${REVIEWS.length} matching reviews (${REVIEWS.length} total)`)).toBeInTheDocument()
    expect(reviewCalls()).toEqual([])
  })
})

describe('re-analyse', () => {
  it('asks first, shows progress, then shows the new run', async () => {
    const pending = deferred()
    let analysisLoads = 0
    mockBackend({
      'GET /health': {},
      'GET /products/7/analysis': () => { analysisLoads += 1; return json(analysisLoads === 1 ? ANALYSIS : { ...ANALYSIS, analysisId: 4 }) },
      'GET /products/7/reviews': serveReviews(),
      'POST /products/7/analyze': () => pending.promise.then(() => json({ ...ANALYSIS, analysisId: 4 })),
    })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Re-analyse' }))
    expect(screen.getByText('Run the analysis again?')).toBeInTheDocument()
    expect(screen.getByText(/Earlier results are kept unchanged/)).toBeInTheDocument()
    const posts = () => fetch.mock.calls.filter(([u, i]) => u.includes('/analyze') && i?.method === 'POST')
    expect(posts()).toHaveLength(0) // nothing happens before confirming

    fireEvent.click(within(screen.getByText('Run the analysis again?').closest('[role="status"]')).getByRole('button', { name: 'Re-analyse' }))
    expect(await screen.findByText(/Re-analysing… this can take/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Re-analysing…/ })).toBeDisabled()
    pending.resolve()
    expect(await screen.findByText('Analysis updated')).toBeInTheDocument()
    await vi.waitFor(() => expect(analysisLoads).toBe(2))
    expect(posts()).toHaveLength(1)
  })

  it('cancel does nothing', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Re-analyse' }))
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Run the analysis again?')).not.toBeInTheDocument()
    expect(fetch.mock.calls.some(([, i]) => i?.method === 'POST')).toBe(false)
  })

  it('shows the server’s reason when it fails', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': ANALYSIS,
      'POST /products/7/analyze': () => json({ detail: 'This product has no reviews to analyse.' }, 422) })
    renderAt('/products/7')
    fireEvent.click(await screen.findByRole('button', { name: 'Re-analyse' }))
    fireEvent.click(within(screen.getByText('Run the analysis again?').closest('[role="status"]')).getByRole('button', { name: 'Re-analyse' }))
    expect(await screen.findByText('Couldn’t re-analyse')).toBeInTheDocument()
    expect(screen.getByText('This product has no reviews to analyse.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Re-analyse' })).toBeEnabled()
  })

  it('is not offered for the built-in demo', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/products/demo')
    await screen.findByText('Reviews analysed')
    expect(screen.queryByRole('button', { name: 'Re-analyse' })).not.toBeInTheDocument()
  })

  it('a product without a usable analysis can be analysed from its page', async () => {
    let analysed = false
    mockBackend({
      'GET /health': {},
      'GET /products/7/analysis': () => (analysed ? json(ANALYSIS)
        : json({ detail: 'This analysis was made by an older version of the app that didn’t keep per-review results. Run the analysis again to see them.' }, 409)),
      'POST /products/7/analyze': () => { analysed = true; return json(ANALYSIS) },
      'GET /products/7/reviews': serveReviews(),
    })
    renderAt('/products/7')
    expect(await screen.findByText('There is no analysis to show yet')).toBeInTheDocument()
    expect(screen.getByText(/older version of the app/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Analyse now' }))
    fireEvent.click(screen.getByRole('button', { name: 'Re-analyse' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Stored Phone' })).toBeInTheDocument()
  })
})

describe('charts and edge cases', () => {
  const show = (analysis) => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': analysis })
    renderAt('/products/7')
  }

  it('sentiment and star ratings are separate charts, plus tone by star rating', async () => {
    show(ANALYSIS)
    expect(await screen.findByText('Tone of the review text')).toBeInTheDocument()
    expect(screen.getByText('Star ratings')).toBeInTheDocument()
    expect(screen.getByText('Tone of the text by star rating')).toBeInTheDocument()
    const five = ANALYSIS.toneByRating.find((r) => r.stars === 5)
    expect(screen.getByRole('img', { name: `5 stars: ${five.positive} positive, ${five.neutral} neutral, ${five.negative} negative` })).toBeInTheDocument()
  })

  it('names the engine in the page header', async () => {
    show(ANALYSIS)
    const titleBlock = (await screen.findByRole('heading', { level: 1, name: 'Stored Phone' })).parentElement
    expect(within(titleBlock).getByText(/Sentiment:/)).toHaveTextContent('Sentiment: RoBERTa sentiment model')
  })

  it('data without star ratings: no rating chart, no tone-by-rating chart', async () => {
    show({ ...ANALYSIS, stats: { ...ANALYSIS.stats, ratedReviews: 0, averageRating: null, ratingSentimentMismatches: [],
      ratingDistribution: ANALYSIS.stats.ratingDistribution.map((r) => ({ ...r, count: 0 })) },
    toneByRating: ANALYSIS.toneByRating.map((r) => ({ ...r, reviews: 0, positive: 0, neutral: 0, negative: 0, notAnalysed: 0 })) })
    expect(await screen.findByText('This data has no star ratings.')).toBeInTheDocument()
    expect(screen.queryByText('Tone of the text by star rating')).not.toBeInTheDocument()
    expect(screen.getByText('No star ratings in data')).toBeInTheDocument()
  })

  it('no review in a supported language: explains instead of showing an empty chart', async () => {
    show({ ...ANALYSIS, stats: { ...ANALYSIS.stats, analysedReviews: 0, notAnalysed: { languageNotSupported: ANALYSIS.stats.totalReviews },
      sentimentCounts: { positive: 0, neutral: 0, negative: 0 }, sentimentPercent: { positive: 0, neutral: 0, negative: 0 } } })
    expect(await screen.findByText(/could be analysed for tone, because none is in English/)).toBeInTheDocument()
    expect(screen.getByText('Reviews analysed').nextSibling).toHaveTextContent('0')
    expect(screen.getAllByText('Not measurable')).toHaveLength(3) // no misleading 0% tiles
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('no features found', async () => {
    mockBackend({ 'GET /health': {}, 'GET /products/7/analysis': { ...ANALYSIS, aspects: [], keywords: [] } })
    renderAt('/products/7?tab=aspects')
    expect(await screen.findByText('No known features were mentioned')).toBeInTheDocument()
    expect(screen.getByText('Not enough reviews to find repeated words.')).toBeInTheDocument()
  })
})

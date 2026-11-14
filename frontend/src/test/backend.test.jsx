// Frontend ↔ backend communication, with fetch mocked to return the backend's real response shapes.
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import demo from '../demo/demoAnalysis.json'
import { api, ApiError } from '../lib/api'
import { filterReviews } from '../lib/reviewFilters'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'

const json = (body, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } }))

const STORED = {
  id: 7, name: 'Uploaded Blender', brand: null, category: null, source: 'upload', sourceUrl: null,
  fileName: 'blender.csv', createdAt: '2026-11-14T10:00:00Z', totalReviews: 63, averageRating: 3.61,
  positivePercent: 65.1, analyzedAt: '2026-11-14T10:00:01Z',
}
// Same shape the backend returns from GET /products/{id}/analysis.
const STORED_ANALYSIS = {
  ...demo,
  analysisId: 3,
  product: { id: 7, name: 'Uploaded Blender', brand: null, category: null, source: 'upload' },
  ingestion: { ...demo.ingestion, fileName: 'blender.csv', invalidRatings: 0, invalidDates: 0, truncated: 0, imported: 63 },
}

/** Route table for the mocked backend: { 'GET /products': body | (init, params) => Promise<Response> }. Query strings are ignored for matching. */
function mockBackend(routes) {
  globalThis.fetch = vi.fn((url, init = {}) => {
    const [path, query = ''] = url.replace(api.baseUrl, '').split('?')
    const handler = routes[`${init.method ?? 'GET'} ${path}`]
    if (handler === undefined) return json({ detail: 'This address doesn’t exist on the API.' }, 404)
    return typeof handler === 'function' ? handler(init, new URLSearchParams(query)) : json(handler)
  })
}

/** A stand-in for GET /products/{id}/reviews, using the same rules as the server (shared fixture test). */
function serveReviews(analysis) {
  return (_init, params) => {
    const filters = { query: params.get('search') ?? '', sentiment: params.get('sentiment') ?? 'all',
      rating: params.get('rating') ?? 'all', sort: params.get('sort') ?? 'newest' }
    const all = filterReviews(analysis.reviews, filters, analysis.stats.ratingSentimentMismatches)
    const offset = Number(params.get('offset') ?? 0)
    const limit = Number(params.get('limit') ?? 20)
    return json({ analysisId: analysis.analysisId, total: all.length, offset, limit, items: all.slice(offset, offset + limit) })
  }
}

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

describe('api client', () => {
  it('sends the upload as multipart form data with the column choices as JSON', async () => {
    mockBackend({ 'POST /uploads/import': STORED })
    const file = new File(['review\nGood'], 'r.csv', { type: 'text/csv' })
    const result = await api.importUpload(file, { productName: 'Blender', columns: { text: 'review', rating: null } })
    expect(result.id).toBe(7)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe(`${api.baseUrl}/uploads/import`)
    expect(init.method).toBe('POST')
    expect(init.body.get('product_name')).toBe('Blender')
    expect(JSON.parse(init.body.get('columns'))).toEqual({ text: 'review', rating: null })
    expect(init.body.get('file').name).toBe('r.csv')
  })

  it('turns backend error bodies into readable errors with the status code', async () => {
    mockBackend({ 'GET /products/9/analysis': () => json({ detail: 'Product 9 doesn’t exist.' }, 404) })
    const error = await api.getAnalysis(9).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(404)
    expect(error.message).toBe('Product 9 doesn’t exist.')
  })

  it('reports an offline server separately from errors', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    const error = await api.health().catch((e) => e)
    expect(error.offline).toBe(true)
  })

  it('builds report download links on the API', () => {
    expect(api.reportUrl(7, 'csv')).toBe(`${api.baseUrl}/products/7/report.csv`)
  })
})

describe('with the backend running', () => {
  it('history lists stored products next to the demo product', async () => {
    mockBackend({ 'GET /health': { status: 'ok' }, 'GET /products': [STORED] })
    renderAt('/history')
    expect(await screen.findByText('Uploaded Blender')).toBeInTheDocument()
    expect(screen.getByText(demo.product.name)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Filter by source'), { target: { value: 'upload' } })
    expect(screen.queryByText(demo.product.name)).not.toBeInTheDocument()
  })

  it('history hides the demo product when demo mode is off', async () => {
    localStorage.setItem('rd-settings', JSON.stringify({ showDemo: false }))
    mockBackend({ 'GET /health': { status: 'ok' }, 'GET /products': [STORED] })
    renderAt('/history')
    expect(await screen.findByText('Uploaded Blender')).toBeInTheDocument()
    expect(screen.queryByText(demo.product.name)).not.toBeInTheDocument()
  })

  it('opens a stored analysis from the backend, without the demo warning', async () => {
    mockBackend({ 'GET /health': { status: 'ok' }, 'GET /products/7/analysis': STORED_ANALYSIS })
    renderAt('/products/7')
    expect(await screen.findByRole('heading', { level: 1, name: 'Uploaded Blender' })).toBeInTheDocument()
    expect(screen.getByText('Uploaded file')).toBeInTheDocument()
    expect(screen.queryByText('Demo data', { selector: 'p' })).not.toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(`${api.baseUrl}/products/7/analysis?include_reviews=false`, {})
  })

  it('shows a clear message for a product that no longer exists', async () => {
    mockBackend({ 'GET /health': { status: 'ok' } })
    renderAt('/products/404')
    expect(await screen.findByText('This product doesn’t exist')).toBeInTheDocument()
  })

  it('upload: preview, import, then open the new analysis', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products': [],
      'POST /uploads/preview': {
        fileName: 'blender.csv', rowCount: 2, columns: ['Comment', 'Stars'],
        sampleRows: [{ Comment: 'Great', Stars: '5' }, { Comment: 'Bad', Stars: '1' }],
        detected: { text: 'Comment', rating: 'Stars', date: null, title: null, reviewer: null, productName: null, id: null },
        productName: null, warnings: ['The file mentions 2 different product names.'],
      },
      'POST /uploads/import': STORED,
      'GET /products/7/analysis': STORED_ANALYSIS,
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['Comment,Stars'], 'blender.csv', { type: 'text/csv' })] } })
    expect(await screen.findByText('The file mentions 2 different product names.')).toBeInTheDocument()
    expect(screen.getByLabelText('Product name')).toHaveValue('blender')
    fireEvent.click(screen.getByRole('button', { name: 'Import and analyse' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Uploaded Blender' })).toBeInTheDocument()
    const importCall = fetch.mock.calls.find(([url]) => url.endsWith('/uploads/import'))
    expect(JSON.parse(importCall[1].body.get('columns'))).toMatchObject({ text: 'Comment', rating: 'Stars' })
  })

  it('upload: shows the backend’s reason when an import is rejected', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'POST /uploads/preview': { fileName: 'r.csv', rowCount: 1, columns: ['review'], sampleRows: [{ review: null }],
        detected: { text: 'review' }, productName: null, warnings: [] },
      'POST /uploads/import': () => json({ detail: 'No usable reviews were found: every row had empty review text.' }, 422),
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['review'], 'r.csv', { type: 'text/csv' })] } })
    fireEvent.click(await screen.findByRole('button', { name: 'Import and analyse' }))
    expect(await screen.findByText(/No usable reviews were found/)).toBeInTheDocument()
  })

  it('upload: large files get a time estimate before and a status message during the import', async () => {
    let finish
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products': [],
      'POST /uploads/preview': { fileName: 'big.csv', rowCount: 12000, columns: ['review'], sampleRows: [{ review: 'Good' }],
        detected: { text: 'review' }, productName: null, warnings: [] },
      'POST /uploads/import': () => new Promise((resolve) => { finish = () => resolve(json({ detail: 'stopped for the test' }, 422)) }),
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['review'], 'big.csv', { type: 'text/csv' })] } })
    expect(await screen.findByText(/Analysing 12,000 reviews takes a while: about 2 minutes/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Import and analyse' }))
    const progress = await screen.findByText('Importing and analysing 12,000 rows… this can take about 2 minutes. Keep this page open.')
    expect(progress.closest('[role="status"]')).not.toBeNull()   // announced to screen readers
    finish()
    expect(await screen.findByText('stopped for the test')).toBeInTheDocument()
  })

  it('upload: small files show no time warning', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'POST /uploads/preview': { fileName: 'r.csv', rowCount: 5000, columns: ['review'], sampleRows: [{ review: 'Good' }],
        detected: { text: 'review' }, productName: null, warnings: [] },
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['review'], 'r.csv', { type: 'text/csv' })] } })
    await screen.findByRole('button', { name: 'Import and analyse' })
    expect(screen.queryByText(/takes a while/)).not.toBeInTheDocument()
  })

  it('unsupported links show the backend’s answer', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products': [],
      'POST /products/from-url': () => json({ detail: 'shop.example.com isn’t a supported website.' }, 422),
    })
    renderAt('/analyze')
    await screen.findByText('Supported websites')
    // Wait for the health check so the form asks the backend.
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith(`${api.baseUrl}/health`, {}))
    fireEvent.change(screen.getByLabelText('Product link'), { target: { value: 'https://shop.example.com/p/1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    expect(await screen.findByText('shop.example.com isn’t supported yet')).toBeInTheDocument()
    const call = fetch.mock.calls.find(([url]) => url.endsWith('/products/from-url'))
    expect(JSON.parse(call[1].body)).toEqual({ url: 'https://shop.example.com/p/1' })
  })

  it('reports: both downloads offered for stored products, an honest message for the demo product', async () => {
    mockBackend({ 'GET /health': { status: 'ok' }, 'GET /products': [STORED], 'GET /history': [] })
    renderAt('/reports')
    await screen.findByRole('option', { name: 'Uploaded Blender' })
    fireEvent.change(screen.getByLabelText('Product'), { target: { value: 'demo' } })
    expect(screen.queryByRole('button', { name: /Download/ })).not.toBeInTheDocument()
    expect(screen.getAllByText(/demo product is built into the app/)).toHaveLength(2)
  })
})

describe('product links (Phase 3)', () => {
  const APPLE_URL = 'https://apps.apple.com/in/app/sample-notes/id1234567890'
  const COLLECTED = {
    ...STORED, id: 9, name: 'Sample Notes', source: 'url', sourceUrl: APPLE_URL, sourceSite: 'apple_app_store',
    sourceSiteName: 'Apple App Store', sourceRegion: 'in', collectedAt: '2026-11-14T10:00:00Z',
  }
  const COLLECTED_ANALYSIS = {
    ...STORED_ANALYSIS,
    product: { id: 9, name: 'Sample Notes', brand: 'Sample Labs', category: 'Productivity', source: 'url',
      sourceUrl: APPLE_URL, sourceSite: 'apple_app_store', sourceSiteName: 'Apple App Store', sourceRegion: 'in',
      collectedAt: '2026-11-14T10:00:00Z' },
    ingestion: { source: 'Apple App Store', region: 'IN', received: 63, imported: 63, newReviews: 63,
      duplicatesRemoved: 0, emptyRemoved: 0, storeRating: 4.6, storeRatingCount: 8319648, pagesRead: 2,
      sourceLimit: 'Apple’s public feed lists at most the 500 most recent written reviews for each country store.' },
  }

  async function submitLink(link) {
    renderAt('/analyze')
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith(`${api.baseUrl}/health`, {}))
    await screen.findByText('Supported websites')
    fireEvent.change(screen.getByLabelText('Product link'), { target: { value: link } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
  }

  it('lists the App Store as supported', async () => {
    mockBackend({ 'GET /health': { status: 'ok' } })
    renderAt('/analyze')
    expect(await screen.findByText('Apple App Store')).toBeInTheDocument()
    expect(screen.getAllByText('Supported')).toHaveLength(2) // demo store + App Store
  })

  it('collects an App Store link and opens the analysis with its source details', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'POST /products/from-url': COLLECTED,
      'GET /products/9/analysis': COLLECTED_ANALYSIS,
    })
    await submitLink(APPLE_URL)
    expect(await screen.findByRole('heading', { level: 1, name: 'Sample Notes' })).toBeInTheDocument()
    expect(screen.getByText('Reviews collected from Apple App Store (IN store)')).toBeInTheDocument()
    expect(screen.getByText(/63 real public reviews, last collected/)).toBeInTheDocument()
    expect(screen.getByText(/500 most recent written reviews/)).toBeInTheDocument()
    expect(screen.getByText(/overall rating is 4\.6 from 83,19,648 ratings/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /View on Apple App Store/ })).toHaveAttribute('href', APPLE_URL)
    expect(screen.queryByText('Demo data', { selector: 'p' })).not.toBeInTheDocument()
  })

  it('collect latest reviews refreshes and reloads the analysis', async () => {
    let analysisCalls = 0
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products/9/analysis': () => { analysisCalls += 1; return json(COLLECTED_ANALYSIS) },
      'POST /products/9/refresh': COLLECTED,
    })
    renderAt('/products/9')
    fireEvent.click(await screen.findByRole('button', { name: 'Collect latest reviews' }))
    await vi.waitFor(() => expect(analysisCalls).toBe(2))
    expect(fetch.mock.calls.some(([url, init]) => url.endsWith('/products/9/refresh') && init.method === 'POST')).toBe(true)
  })

  it('shows the reason when refreshing fails', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products/9/analysis': COLLECTED_ANALYSIS,
      'POST /products/9/refresh': () => json({ detail: 'Apple App Store took too long to respond.' }, 504),
    })
    renderAt('/products/9')
    fireEvent.click(await screen.findByRole('button', { name: 'Collect latest reviews' }))
    expect(await screen.findByText('Apple App Store took too long to respond.')).toBeInTheDocument()
  })

  it.each([
    [404, 'No app with ID 1234567890 was found in the App Store for country “IN”.', 'Product not found'],
    [422, '“Sample Notes” has no written reviews in the IN App Store yet.', 'Couldn’t collect reviews from this link'],
    [504, 'Apple App Store took too long to respond. Please try again in a minute.', 'Couldn’t get reviews from Apple App Store'],
    [502, 'Couldn’t connect to Apple App Store.', 'Couldn’t get reviews from Apple App Store'],
  ])('a %s from the backend shows its message', async (status, detail, title) => {
    mockBackend({ 'GET /health': { status: 'ok' }, 'POST /products/from-url': () => json({ detail }, status) })
    await submitLink(APPLE_URL)
    expect(await screen.findByText(title)).toBeInTheDocument()
    expect(screen.getByText(detail)).toBeInTheDocument()
  })

  it('explains that collecting needs the server when it is offline', async () => {
    globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    renderAt('/analyze')
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled())
    await screen.findByText('Supported websites')
    fireEvent.change(screen.getByLabelText('Product link'), { target: { value: APPLE_URL } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    expect(await screen.findByText(/Collecting reviews from Apple App Store needs the backend/)).toBeInTheDocument()
  })

  it('Amazon links are explained without contacting the server', async () => {
    mockBackend({ 'GET /health': { status: 'ok' } })
    await submitLink('https://www.amazon.in/dp/B0ABCDEFGH')
    expect(await screen.findByText('Amazon reviews can’t be collected automatically')).toBeInTheDocument()
    expect(fetch.mock.calls.some(([url]) => url.endsWith('/products/from-url'))).toBe(false)
  })
})

describe('NLP results (Phase 4)', () => {
  const HINGLISH = {
    id: 'H-1', text: 'bakwas app hai, paisa barbaad', rating: 1, date: '2026-11-01', title: null, reviewer: null,
    sentiment: null, score: null, mixed: false, aspects: [], status: 'language_not_supported', language: 'hinglish', usedTitle: false,
  }
  const withLanguage = {
    ...STORED_ANALYSIS,
    reviews: [...STORED_ANALYSIS.reviews, HINGLISH],
    stats: { ...STORED_ANALYSIS.stats, totalReviews: STORED_ANALYSIS.stats.totalReviews + 1,
      analysedReviews: STORED_ANALYSIS.stats.totalReviews, notAnalysed: { languageNotSupported: 1 } },
    engine: { id: 'transformer', name: 'RoBERTa sentiment model', pipelineVersion: 2, fallbackReason: null, domain: 'product' },
  }
  const render7 = (analysis, path = '/products/7') => {
    mockBackend({ 'GET /health': { status: 'ok' }, 'GET /products/7/analysis': analysis,
      'GET /products/7/reviews': serveReviews(analysis) })
    renderAt(path)
  }

  it('names the engine that produced the run', async () => {
    render7(withLanguage)
    expect(await screen.findAllByText('RoBERTa sentiment model')).toHaveLength(2) // page header + method note
    expect(screen.getByText(/chance it is positive minus the chance it is negative/)).toBeInTheDocument()
  })

  it('warns when the run fell back to VADER', async () => {
    render7({ ...withLanguage, engine: { id: 'vader', pipelineVersion: 2, fallbackReason: 'The sentiment model couldn’t be used, so VADER was used instead (model files are not installed).' } })
    expect(await screen.findByText('Analysed with the backup method')).toBeInTheDocument()
    expect(screen.getAllByText('VADER (rule-based)')).toHaveLength(2)
    expect(screen.getByText('(backup method)')).toBeInTheDocument()
    expect(screen.getByText(/between −0.05 and \+0.05 count as neutral/)).toBeInTheDocument()
  })

  it('says when an old run used the earlier method', async () => {
    render7({ ...STORED_ANALYSIS, engine: { id: 'vader', pipelineVersion: 1 } })
    expect(await screen.findByText(/made with an earlier version of the method/)).toBeInTheDocument()
  })

  it('counts only analysed reviews and says how many were not in English', async () => {
    render7(withLanguage)
    const total = withLanguage.stats.totalReviews
    expect((await screen.findByText('Reviews analysed')).nextSibling).toHaveTextContent(String(total - 1))
    expect(screen.getByText(new RegExp(`1 of ${total} not in English`))).toBeInTheDocument()
  })

  it('shows non-English reviews as not analysed, with a reason, and lets you filter them', async () => {
    render7(withLanguage, '/products/7?tab=reviews')
    fireEvent.change(await screen.findByLabelText('Filter by sentiment'), { target: { value: 'unanalysed' } })
    expect(screen.getByText(/Showing 1 of 1 matching reviews/)).toBeInTheDocument()
    expect(screen.getByText('Not analysed')).toBeInTheDocument()
    fireEvent.click(screen.getByText('bakwas app hai, paisa barbaad'))
    expect(screen.getByText(/looks like Hindi written in English letters/)).toBeInTheDocument()
    expect(screen.getAllByText('Not analysed').length).toBeGreaterThan(1) // badge + score
  })

  it('sorting by sentiment puts unscored reviews last instead of breaking', async () => {
    render7(withLanguage, '/products/7?tab=reviews')
    fireEvent.change(await screen.findByLabelText('Sort reviews'), { target: { value: 'negative' } })
    expect(screen.getByText(/Showing 20 of/)).toBeInTheDocument()
    expect(screen.queryByText('bakwas app hai, paisa barbaad')).not.toBeInTheDocument() // last, beyond the first 20
  })

  it('app products describe app features when none were found', async () => {
    render7({ ...withLanguage, product: { ...withLanguage.product, domain: 'app' }, aspects: [] }, '/products/7?tab=aspects')
    expect(await screen.findByText(/login, crashes, speed, updates, ads/)).toBeInTheDocument()
  })

  it('upload sends what the reviews describe', async () => {
    mockBackend({
      'GET /health': { status: 'ok' },
      'GET /products': [],
      'POST /uploads/preview': { fileName: 'r.csv', rowCount: 1, columns: ['review'], sampleRows: [{ review: 'Crashes' }],
        detected: { text: 'review' }, productName: null, warnings: [] },
      'POST /uploads/import': STORED,
      'GET /products/7/analysis': withLanguage,
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['review'], 'r.csv', { type: 'text/csv' })] } })
    fireEvent.change(await screen.findByLabelText('What do these reviews describe?'), { target: { value: 'app' } })
    fireEvent.click(screen.getByRole('button', { name: 'Import and analyse' }))
    await screen.findByRole('heading', { level: 1, name: 'Uploaded Blender' })
    const call = fetch.mock.calls.find(([url]) => url.endsWith('/uploads/import'))
    expect(call[1].body.get('domain')).toBe('app')
  })
})

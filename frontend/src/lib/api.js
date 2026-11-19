// Single place for talking to the FastAPI backend.
import { STATIC_DEMO, STATIC_DEMO_MESSAGE } from './staticDemo'

// The static demo has no backend, so it carries no API address at all (not even the default one): STATIC_DEMO is a
// build-time constant, and the bundler drops the other branch from the demo build.
const API_URL = STATIC_DEMO
  ? ''
  : (import.meta.env.VITE_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { status, offline = false } = {}) {
    super(message)
    this.status = status
    this.offline = offline
  }
}

// The identity-provider integration can supply its current/refreshed access token per request.
// No passwords, refresh tokens or browser-persisted secrets are managed by this API client.
let accessTokenProvider = null
let unauthorized = null
let requestEpoch = 0
const pendingRequests = new Set()
const downloadUrls = new Set()

const cancelled = () => new DOMException('The account session changed. This result was discarded.', 'AbortError')

export function invalidateAuthenticatedRequests() {
  if (STATIC_DEMO) return
  requestEpoch++
  for (const controller of pendingRequests) controller.abort()
  pendingRequests.clear()
  for (const url of downloadUrls) URL.revokeObjectURL(url)
  downloadUrls.clear()
}

export function setAccessTokenProvider(provider, { onUnauthorized = null } = {}) {
  if (STATIC_DEMO) return
  if (provider !== null && typeof provider !== 'function') throw new TypeError('Expected a token provider or null')
  invalidateAuthenticatedRequests()
  accessTokenProvider = provider
  unauthorized = onUnauthorized
}

async function authenticatedOptions(options = {}) {
  if (STATIC_DEMO || !accessTokenProvider) return options
  let token
  try {
    token = await accessTokenProvider()
  } catch {
    throw new ApiError('Couldn’t verify your session. Sign in again.', { status: 401 })
  }
  if (typeof token !== 'string' || !token.trim()) {
    throw new ApiError('Sign in to access your review data.', { status: 401 })
  }
  return { ...options, headers: { ...options.headers, Authorization: `Bearer ${token}` } }
}

async function request(path, options = {}) {
  if (STATIC_DEMO) throw new ApiError(STATIC_DEMO_MESSAGE, { offline: true })   // never contact any server
  return scopedRequest(`${API_URL}${path}`, options, async (response, scope) => {
    const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null
    scope.check()
    if (!response.ok) {
      scope.reject(response.status)
      const detail = body?.detail
      const message = typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status}).`
      throw new ApiError(message, { status: response.status })
    }
    return body
  })
}

async function scopedRequest(url, options, consume) {
  const epoch = requestEpoch
  const check = () => { if (epoch !== requestEpoch) throw cancelled() }
  let authenticated
  try { authenticated = await authenticatedOptions(options) } catch (err) { check(); throw err }
  check() // a refresh or sign-out may have changed accounts while acquiring the token
  const controller = accessTokenProvider ? new AbortController() : null
  if (controller) pendingRequests.add(controller)
  const token = authenticated.headers?.Authorization?.slice(7)
  const reject = (status) => { if (status === 401 && token) unauthorized?.(token) }
  let response
  try {
    try {
      const signal = controller && authenticated.signal
        ? AbortSignal.any([controller.signal, authenticated.signal]) : controller?.signal ?? authenticated.signal
      response = await fetch(url, signal ? { ...authenticated, signal } : authenticated)
    } catch (err) {
      check()
      if (err.name === 'AbortError') throw err
      throw new ApiError('Can’t reach the analysis server. Make sure the backend is running.', { offline: true })
    }
    check()
    return await consume(response, { check, reject })
  } finally {
    if (controller) pendingRequests.delete(controller)
  }
}

export const api = {
  baseUrl: API_URL,
  health: () => request('/health'),
  listProducts: () => request('/products'),
  // The dashboard pages through reviews separately, so the analysis is loaded without them.
  getAnalysis: (productId) => request(`/products/${encodeURIComponent(productId)}/analysis?include_reviews=false`),
  reanalyze: (productId) =>
    request(`/products/${encodeURIComponent(productId)}/analyze?include_reviews=false`, { method: 'POST' }),
  listReviews: (productId, { analysisId, sentiment = 'all', rating = 'all', query = '', sort = 'newest', offset = 0, limit = 20 }) => {
    const params = new URLSearchParams({ sentiment, rating: String(rating), sort, offset: String(offset), limit: String(limit) })
    if (analysisId) params.set('analysis_id', String(analysisId))
    if (query.trim()) params.set('search', query.trim())
    return request(`/products/${encodeURIComponent(productId)}/reviews?${params}`)
  },
  getReview: (productId, reviewId, analysisId) =>
    request(`/products/${encodeURIComponent(productId)}/reviews/${encodeURIComponent(reviewId)}${analysisId ? `?analysis_id=${analysisId}` : ''}`),
  analyzeUrl: (url) =>
    request('/products/from-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  refreshProduct: (productId) => request(`/products/${encodeURIComponent(productId)}/refresh`, { method: 'POST' }),
  previewUpload: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/uploads/preview', { method: 'POST', body: form })
  },
  uploadLimits: () => request('/uploads/limits'),
  importStatus: (key) => request(`/uploads/import-status/${encodeURIComponent(key)}`, { cache: 'no-store' }),
  importUpload: (file, { productName, columns, domain = 'product', key }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('product_name', productName)
    form.append('columns', JSON.stringify(columns))
    form.append('domain', domain)
    return request('/uploads/import', {
      method: 'POST', body: form,
      ...(key ? { headers: { 'Idempotency-Key': key }, signal: AbortSignal.timeout(40000) } : {}),
    })
  },
  reportUrl: (productId, format, analysisId) =>
    `${API_URL}/products/${encodeURIComponent(productId)}/report.${format}${analysisId ? `?analysis_id=${analysisId}` : ''}`,
  aiStatus: () => request('/ai/status'),
  getAiSummary: (productId, analysisId) =>
    request(`/products/${encodeURIComponent(productId)}/ai-summary?analysis_id=${analysisId}`),
  createAiSummary: (productId, analysisId) =>
    request(`/products/${encodeURIComponent(productId)}/ai-summary?analysis_id=${analysisId}`, { method: 'POST' }),
  listHistory: (productId) => request(`/history?product_id=${encodeURIComponent(productId)}`),
  /** Two stored runs side by side; a missing analysis ID means that product's latest run. */
  compare: ({ productA, productB, analysisA, analysisB }) => {
    const params = new URLSearchParams({ product_a: String(productA), product_b: String(productB) })
    if (analysisA) params.set('analysis_a', String(analysisA))
    if (analysisB) params.set('analysis_b', String(analysisB))
    return request(`/compare?${params}`)
  },
  /** Downloads a report file. Resolves to the file name; rejects with ApiError (e.g. the server's reason). */
  downloadReport: async (productId, format, analysisId) => {
    if (STATIC_DEMO) throw new ApiError(STATIC_DEMO_MESSAGE, { offline: true })
    return scopedRequest(api.reportUrl(productId, format, analysisId), {}, async (response, scope) => {
      if (!response.ok) {
        const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null
        scope.check()
        scope.reject(response.status)
        throw new ApiError(typeof body?.detail === 'string' ? body.detail : `Download failed (${response.status}).`, { status: response.status })
      }
      const name = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? `report.${format}`
      const blob = await response.blob()
      scope.check() // never create/click a download from a previous account, even if abort was ignored
      const url = URL.createObjectURL(blob)
      downloadUrls.add(url)
      const link = Object.assign(document.createElement('a'), { href: url, download: name })
      document.body.append(link)
      link.click()
      link.remove()
      setTimeout(() => { if (downloadUrls.delete(url)) URL.revokeObjectURL(url) }, 1000)
      return name
    })
  },
}

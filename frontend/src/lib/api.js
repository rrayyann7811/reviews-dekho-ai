// Single place for talking to the FastAPI backend.
const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(message, { status, offline = false } = {}) {
    super(message)
    this.status = status
    this.offline = offline
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_URL}${path}`, options)
  } catch {
    throw new ApiError('Can’t reach the analysis server. Make sure the backend is running.', { offline: true })
  }
  const body = response.headers.get('content-type')?.includes('application/json') ? await response.json() : null
  if (!response.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status}).`
    throw new ApiError(message, { status: response.status })
  }
  return body
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
  importUpload: (file, { productName, columns, domain = 'product' }) => {
    const form = new FormData()
    form.append('file', file)
    form.append('product_name', productName)
    form.append('columns', JSON.stringify(columns))
    form.append('domain', domain)
    return request('/uploads/import', { method: 'POST', body: form })
  },
  reportUrl: (productId, format) => `${API_URL}/products/${encodeURIComponent(productId)}/report.${format}`,
}

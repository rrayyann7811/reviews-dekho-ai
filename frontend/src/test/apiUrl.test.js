// The normal (non-demo) build keeps its API address: VITE_API_URL if set, otherwise the local default.
import { describe, expect, it } from 'vitest'
import { api } from '../lib/api'
import { STATIC_DEMO } from '../lib/staticDemo'

describe('API address in the normal build', () => {
  it('uses the configured or default backend address', () => {
    expect(STATIC_DEMO).toBe(false)
    const expected = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api').replace(/\/$/, '')
    expect(api.baseUrl).toBe(expected)
    expect(api.reportUrl(7, 'csv', 3)).toBe(`${expected}/products/7/report.csv?analysis_id=3`)
  })
})

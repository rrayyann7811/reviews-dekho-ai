import { describe, expect, it } from 'vitest'
import demo from '../demo/demoAnalysis.json'
import { validateReviewFile } from '../lib/files'
import { describeEngine } from '../lib/engine'
import { DEFAULT_FILTERS, filterReviews } from '../lib/reviewFilters'
import { detectSite, parseProductUrl } from '../lib/sites'

describe('parseProductUrl', () => {
  it('rejects empty input and non-URLs', () => {
    expect(parseProductUrl('   ').error).toMatch(/Enter a product link/)
    expect(parseProductUrl('not a link').error).toBeTruthy()
    expect(parseProductUrl('ftp://example.com/x').error).toBeTruthy()
  })
  it('adds https when the scheme is missing', () => {
    expect(parseProductUrl('www.flipkart.com/item/p/itm123').url.href).toBe('https://www.flipkart.com/item/p/itm123')
  })
})

describe('detectSite', () => {
  const site = (u) => detectSite(parseProductUrl(u).url)?.id ?? null
  it('recognises known websites including subdomains', () => {
    expect(site('https://www.amazon.in/dp/B0ABCDEFGH')).toBe('amazon')
    expect(site('https://dl.flipkart.com/s/abc')).toBe('flipkart')
    expect(site('https://demo.reviewsdekho.test/product/kestrel-orbit-5g')).toBe('demo')
  })
  it('does not match look-alike domains', () => {
    expect(site('https://notamazon.in/dp/x')).toBeNull()
    expect(site('https://amazon.in.evil.com/dp/x')).toBeNull()
  })
})

describe('validateReviewFile', () => {
  const file = (name, size) => ({ name, size })
  it('accepts CSV and XLSX within the size limit', () => {
    expect(validateReviewFile(file('reviews.csv', 1000))).toBeNull()
    expect(validateReviewFile(file('Reviews.XLSX', 1000))).toBeNull()
  })
  it('rejects other types, empty files and large files', () => {
    expect(validateReviewFile(file('reviews.xls', 1000))).toMatch(/re-saved as .xlsx/)
    expect(validateReviewFile(file('reviews.pdf', 1000))).toMatch(/isn’t a CSV/)
    expect(validateReviewFile(file('reviews.csv', 0))).toMatch(/empty/)
    expect(validateReviewFile(file('reviews.csv', 11 * 1024 * 1024))).toMatch(/limit/)
  })
})

describe('filterReviews', () => {
  const reviews = demo.reviews
  const run = (patch) => filterReviews(reviews, { ...DEFAULT_FILTERS, ...patch }, demo.stats.ratingSentimentMismatches)

  it('returns everything by default, newest first', () => {
    const result = run({})
    expect(result).toHaveLength(reviews.length)
    expect(result[0].date >= result.at(-1).date).toBe(true)
  })
  it('filters by sentiment and matches the reported counts', () => {
    for (const key of ['positive', 'neutral', 'negative']) {
      expect(run({ sentiment: key })).toHaveLength(demo.stats.sentimentCounts[key])
    }
  })
  it('filters by star rating, including missing ratings', () => {
    expect(run({ rating: '5' }).every((r) => r.rating === 5)).toBe(true)
    expect(run({ rating: '5' })).toHaveLength(demo.stats.ratingDistribution.find((d) => d.stars === 5).count)
    expect(run({ rating: 'none' }).every((r) => r.rating === null)).toBe(true)
  })
  it('searches text case-insensitively and finds rating/text mismatches', () => {
    expect(run({ query: 'BATTERY' }).every((r) => `${r.title} ${r.text}`.toLowerCase().includes('battery'))).toBe(true)
    expect(run({ sentiment: 'mismatch' }).map((r) => r.id)).toEqual(demo.stats.ratingSentimentMismatches)
  })
  it('sorts by score', () => {
    const result = run({ sort: 'negative' })
    expect(result[0].score).toBeLessThanOrEqual(result[1].score)
  })
})

describe('Phase 4 helpers', () => {
  it('filters and sorts reviews that have no sentiment', () => {
    const reviews = [
      { id: 'a', text: 'x', sentiment: 'positive', score: 0.9 },
      { id: 'b', text: 'y', sentiment: null, score: null, status: 'language_not_supported' },
      { id: 'c', text: 'z', sentiment: 'negative', score: -0.8 },
    ]
    expect(filterReviews(reviews, { ...DEFAULT_FILTERS, sentiment: 'unanalysed' }).map((r) => r.id)).toEqual(['b'])
    expect(filterReviews(reviews, { ...DEFAULT_FILTERS, sort: 'positive' }).map((r) => r.id)).toEqual(['a', 'c', 'b'])
    expect(filterReviews(reviews, { ...DEFAULT_FILTERS, sort: 'negative' }).map((r) => r.id)).toEqual(['c', 'a', 'b'])
  })

  it('describes each engine', () => {
    expect(describeEngine({ id: 'transformer', pipelineVersion: 2 }).name).toBe('RoBERTa sentiment model')
    expect(describeEngine({ id: 'vader', pipelineVersion: 2 })).toMatchObject({ name: 'VADER (rule-based)', outdated: false })
    expect(describeEngine(null).outdated).toBe(true)
  })
})

// Search, filter and sort logic for the review explorer (kept separate so it can be unit-tested).

export const DEFAULT_FILTERS = { query: '', sentiment: 'all', rating: 'all', sort: 'newest' }

// Reviews without a score (not analysed) always sort last.
const byScore = (direction) => (a, b) => {
  if (a.score == null || b.score == null) return (a.score == null) - (b.score == null)
  return direction * (b.score - a.score)
}

const SORTERS = {
  newest: (a, b) => (b.date ?? '').localeCompare(a.date ?? ''),
  oldest: (a, b) => (a.date ?? '￿').localeCompare(b.date ?? '￿'),
  positive: byScore(1),
  negative: byScore(-1),
}

/** Apply search, filters and sorting. Exported for unit tests. */
export function filterReviews(reviews, filters, mismatchIds = []) {
  const q = filters.query.trim().toLowerCase()
  return reviews
    .filter((r) => {
      if (filters.sentiment === 'mixed') return r.mixed
      if (filters.sentiment === 'mismatch') return mismatchIds.includes(r.id)
      if (filters.sentiment === 'unanalysed') return r.sentiment == null
      return filters.sentiment === 'all' || r.sentiment === filters.sentiment
    })
    .filter((r) => {
      if (filters.rating === 'all') return true
      if (filters.rating === 'none') return r.rating === null || r.rating === undefined
      return r.rating === Number(filters.rating)
    })
    .filter((r) => !q || `${r.title ?? ''} ${r.text} ${r.reviewer ?? ''}`.toLowerCase().includes(q))
    .sort(SORTERS[filters.sort])
}

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { filterReviews } from './reviewFilters'

export const PAGE_SIZE = 20

/**
 * Pages of reviews for the review explorer.
 *
 * `source` is either
 *   { kind: 'local', reviews, mismatchIds }        the offline demo: filtered in the browser
 *   { kind: 'remote', productId, analysisId }      stored products: the server filters, sorts and pages
 * Both follow the same rules (a shared test fixture checks they agree).
 *
 * Returns { items, total, loading, error, hasMore, loadMore, retry }.
 */
export function useReviewPages(source, filters) {
  const local = source.kind === 'local'
  const [limit, setLimit] = useState(PAGE_SIZE)
  const localVisible = useMemo(
    () => (local ? filterReviews(source.reviews, filters, source.mismatchIds) : []),
    [local, source.reviews, source.mismatchIds, filters],
  )

  const [remote, setRemote] = useState({ key: null, items: [], total: 0, loading: true, error: null })
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(0)
  const key = local ? null : JSON.stringify([source.productId, source.analysisId, filters, attempt])

  const fetchPage = useCallback((offset, append) => {
    const id = ++requestId.current
    setRemote((r) => ({ ...r, loading: true, error: null }))
    return api.listReviews(source.productId, { ...filters, analysisId: source.analysisId, offset, limit: PAGE_SIZE })
      .then((page) => {
        if (id !== requestId.current) return // a newer request replaced this one
        setRemote((r) => ({ key, items: append ? [...r.items, ...page.items] : page.items, total: page.total, loading: false, error: null }))
      })
      .catch((error) => id === requestId.current && setRemote((r) => ({ ...r, key, loading: false, error })))
  }, [source.productId, source.analysisId, filters, key])

  // New filters (or a new run) start again from the first page. Typing in the search box waits briefly.
  useEffect(() => {
    if (local) return
    const timer = setTimeout(() => fetchPage(0, false), filters.query ? 250 : 0)
    return () => clearTimeout(timer)
  }, [local, fetchPage, filters.query])

  // The local list also restarts at the first page when the filters change.
  const [limitFor, setLimitFor] = useState(filters)
  if (local && limitFor !== filters) {
    setLimitFor(filters)
    setLimit(PAGE_SIZE)
  }

  if (local) {
    return {
      items: localVisible.slice(0, limit), total: localVisible.length, loading: false, error: null,
      hasMore: localVisible.length > limit, loadMore: () => setLimit((l) => l + PAGE_SIZE), retry: () => {},
    }
  }
  const current = remote.key === key
  return {
    items: current ? remote.items : [], total: current ? remote.total : 0,
    loading: remote.loading || !current, error: current ? remote.error : null,
    hasMore: current && remote.items.length < remote.total,
    loadMore: () => fetchPage(remote.items.length, true),
    retry: () => setAttempt((a) => a + 1),
  }
}

/** One review (for "Read review"), from the demo data or the server. */
export function useReview(source, reviewId) {
  const [state, setState] = useState({ id: null, review: null, error: null })
  const local = source.kind === 'local'
  useEffect(() => {
    if (local || !reviewId) return
    let active = true
    api.getReview(source.productId, reviewId, source.analysisId)
      .then((review) => active && setState({ id: reviewId, review, error: null }))
      .catch((error) => active && setState({ id: reviewId, review: null, error }))
    return () => { active = false }
  }, [local, source.productId, source.analysisId, reviewId])
  if (!reviewId) return { review: null, loading: false, error: null }
  if (local) {
    const review = source.reviews.find((r) => r.id === reviewId) ?? null
    return { review, loading: false, error: review ? null : new Error('This review isn’t in this analysis.') }
  }
  const current = state.id === reviewId
  return { review: current ? state.review : null, loading: !current, error: current ? state.error : null }
}

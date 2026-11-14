import { ChevronDown, Search, SearchX, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { formatDate } from '../../lib/format'
import { DEFAULT_FILTERS } from '../../lib/reviewFilters'
import { PAGE_SIZE, useReview, useReviewPages } from '../../lib/useReviewPages'
import Alert from '../ui/Alert'
import { Badge, SentimentBadge } from '../ui/Badge'
import Button from '../ui/Button'
import EmptyState from '../ui/EmptyState'
import { Input, Select } from '../ui/Field'
import Spinner from '../ui/Spinner'
import Stars from '../ui/Stars'

const LANGUAGE_NOTE = {
  hinglish: 'This review looks like Hindi written in English letters (Hinglish).',
  unknown: 'This review doesn’t look like English.',
}

function ReviewItem({ review, expanded, onToggle, mismatch, as: Tag = 'li' }) {
  return (
    <Tag className={`border-t border-line first:border-t-0 ${expanded ? 'bg-subtle' : ''}`}>
      <button type="button" onClick={onToggle} aria-expanded={expanded} className="flex w-full gap-4 px-5 py-4 text-left hover:bg-subtle">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Stars value={review.rating} />
            {review.title && <span className="text-sm font-medium text-ink">{review.title}</span>}
          </div>
          <p className={`mt-1.5 text-sm text-ink-2 ${expanded ? '' : 'line-clamp-2'}`}>{review.text}</p>
          <p className="mt-1.5 text-xs text-ink-3">
            {review.reviewer ?? 'Anonymous'} · {formatDate(review.date)}
            {review.status === 'language_not_supported' && review.language?.endsWith('script') && ` · Written in ${review.language}`}
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <SentimentBadge value={review.sentiment} />
          {review.mixed && <Badge variant="mixed">Mixed opinion</Badge>}
          <ChevronDown aria-hidden className={`mt-1 size-4 text-ink-3 transition-transform ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>
      {expanded && (
        <div className="space-y-3 px-5 pb-4 text-[13px]">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div><dt className="text-ink-3">Sentiment score</dt><dd className="font-medium tabular-nums">{review.score == null ? 'Not analysed' : `${review.score > 0 ? '+' : ''}${review.score.toFixed(2)}`}</dd></div>
            <div><dt className="text-ink-3">Star rating</dt><dd className="font-medium">{review.rating ? `${review.rating} / 5` : 'Not given'}</dd></div>
            <div><dt className="text-ink-3">Review ID</dt><dd className="font-medium">{review.id}</dd></div>
            <div><dt className="text-ink-3">Date</dt><dd className="font-medium">{formatDate(review.date)}</dd></div>
          </dl>
          {review.status === 'language_not_supported' && (
            <p className="rounded-md border border-line bg-subtle px-3 py-2 text-ink-2">
              {LANGUAGE_NOTE[review.language] ?? 'This review doesn’t look like English.'} The sentiment engines only
              understand English, so its tone wasn’t analysed and it isn’t counted in the percentages. Its star rating still counts.
            </p>
          )}
          {review.usedTitle && (
            <p className="text-ink-3">The text is very short, so the title was analysed with it.</p>
          )}
          {mismatch && (
            <p className="rounded-md border border-mix/25 bg-mix-soft px-3 py-2 text-ink-2">
              The star rating and the wording of this review point in different directions. Neither is treated as more reliable.
            </p>
          )}
          <div>
            <p className="text-ink-3">Features mentioned</p>
            {review.aspects.length === 0 ? (
              <p className="mt-1 text-ink-2">No known features detected.</p>
            ) : (
              <ul className="mt-1.5 space-y-1.5">
                {review.aspects.map((a) => (
                  <li key={a.aspect} className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium text-ink">{a.aspect}</span>
                    <SentimentBadge value={a.sentiment} />
                    <span className="text-ink-3">“{a.snippet}”</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Tag>
  )
}

/** "Read review": the chosen review, pinned above the list whichever page it is on. */
function SelectedReview({ source, reviewId, mismatchIds, onClose }) {
  const { review, loading, error } = useReview(source, reviewId)
  const ref = useRef(null)
  useEffect(() => {
    if (review) ref.current?.scrollIntoView?.({ block: 'nearest' })
  }, [review])
  return (
    <section ref={ref} aria-label="Selected review" className="border-b border-line">
      <div className="flex items-center justify-between bg-brand-50 px-5 py-2 text-[13px]">
        <span className="font-medium text-brand-700">Selected review</span>
        <button type="button" onClick={onClose} className="inline-flex items-center gap-1 font-medium text-brand-600 hover:underline">
          <X aria-hidden className="size-3.5" /> Back to all reviews
        </button>
      </div>
      {loading && <div className="px-5 py-4"><Spinner label="Loading review…" /></div>}
      {error && <Alert variant="error" className="m-5">{error.message}</Alert>}
      {review && <ReviewItem as="div" review={review} expanded onToggle={() => {}} mismatch={mismatchIds.includes(review.id)} />}
    </section>
  )
}

/**
 * `source`: { kind: 'local', reviews, mismatchIds } for the demo, or { kind: 'remote', productId, analysisId }.
 * `focus` is { id, seq }; seq changes on every request so the same review can be selected twice.
 */
export default function ReviewExplorer({ source, totalReviews, mismatchIds, filters, onFiltersChange, focus }) {
  const [expanded, setExpanded] = useState(() => new Set())
  const [selected, setSelected] = useState(focus?.id ?? null)
  const [focusSeq, setFocusSeq] = useState(focus?.seq)
  if (focus?.seq !== focusSeq) { // a new "Read review" request
    setFocusSeq(focus?.seq)
    setSelected(focus?.id ?? null)
  }
  const page = useReviewPages(source, filters)
  const set = (patch) => onFiltersChange({ ...filters, ...patch })

  const toggle = (id) => setExpanded((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const isFiltered = JSON.stringify(filters) !== JSON.stringify(DEFAULT_FILTERS)
  const firstLoad = page.loading && page.items.length === 0

  return (
    <div className="rounded-lg border border-line bg-surface">
      {selected && <SelectedReview source={source} reviewId={selected} mismatchIds={mismatchIds} onClose={() => setSelected(null)} />}
      <div className="grid gap-2 border-b border-line px-5 py-3 sm:grid-cols-2 lg:grid-cols-[1fr_190px_150px_170px]">
        <div className="relative sm:col-span-2 lg:col-span-1">
          <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
          <Input aria-label="Search reviews" placeholder="Search reviews" className="pl-9" value={filters.query} onChange={(e) => set({ query: e.target.value })} />
        </div>
        <Select aria-label="Filter by sentiment" value={filters.sentiment} onChange={(e) => set({ sentiment: e.target.value })}>
          <option value="all">All sentiments</option>
          <option value="positive">Positive</option>
          <option value="neutral">Neutral</option>
          <option value="negative">Negative</option>
          <option value="mixed">Mixed opinions</option>
          <option value="mismatch">Stars disagree with text</option>
          <option value="unanalysed">Not analysed (language)</option>
        </Select>
        <Select aria-label="Filter by star rating" value={filters.rating} onChange={(e) => set({ rating: e.target.value })}>
          <option value="all">All ratings</option>
          {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} star{n === 1 ? '' : 's'}</option>)}
          <option value="none">No rating</option>
        </Select>
        <Select aria-label="Sort reviews" value={filters.sort} onChange={(e) => set({ sort: e.target.value })}>
          <option value="newest">Newest first</option>
          <option value="oldest">Oldest first</option>
          <option value="positive">Most positive first</option>
          <option value="negative">Most negative first</option>
        </Select>
      </div>

      <div className="flex items-center justify-between px-5 py-2.5 text-[13px] text-ink-3" aria-live="polite">
        <span>{firstLoad ? 'Loading reviews…' : `Showing ${page.items.length} of ${page.total} matching reviews (${totalReviews} total)`}</span>
        {isFiltered && <button type="button" className="font-medium text-brand-600 hover:underline" onClick={() => set(DEFAULT_FILTERS)}>Clear filters</button>}
      </div>

      {page.error ? (
        <Alert variant="error" title="Couldn’t load reviews" className="m-5"
          action={<Button variant="secondary" size="sm" onClick={page.retry}>Try again</Button>}>
          {page.error.message}
        </Alert>
      ) : firstLoad ? (
        <div className="border-t border-line px-5 py-8"><Spinner label="Loading reviews…" /></div>
      ) : page.items.length === 0 ? (
        <EmptyState icon={SearchX} title={totalReviews === 0 ? 'No reviews' : 'No reviews match these filters'} className="border-t border-line"
          action={isFiltered && <Button variant="secondary" onClick={() => set(DEFAULT_FILTERS)}>Clear filters</Button>} />
      ) : (
        <ul className="border-t border-line">
          {page.items.map((r) => (
            <ReviewItem key={r.id} review={r} expanded={expanded.has(r.id)} onToggle={() => toggle(r.id)}
              mismatch={mismatchIds.includes(r.id)} />
          ))}
        </ul>
      )}
      {page.hasMore && !page.error && (
        <div className="border-t border-line px-5 py-3 text-center">
          <Button variant="secondary" onClick={page.loadMore} disabled={page.loading}>
            {page.loading ? 'Loading…' : `Show ${Math.min(PAGE_SIZE, page.total - page.items.length)} more`}
          </Button>
        </div>
      )}
    </div>
  )
}

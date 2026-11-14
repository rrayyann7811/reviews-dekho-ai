import { formatPercent, formatRating, plural } from '../../lib/format'
import Panel from '../ui/Panel'
import Stars from '../ui/Stars'
import { differenceText } from '../../lib/compareText'
import { SeparationBadge, ShareBar, SideTag } from './parts'

const TONES = [
  { key: 'positive', label: 'Positive' },
  { key: 'neutral', label: 'Neutral' },
  { key: 'negative', label: 'Negative' },
]

function notMeasurableReason(side) {
  if (side.counts.analysed === 0) return 'Not measurable: none of its reviews could be analysed.'
  return 'Not measurable: this older run didn’t store sentiment counts.'
}

function SideShare({ side, data, value, tone, label }) {
  return (
    <div className="grid grid-cols-[1.25rem_minmax(0,1fr)] items-start gap-2.5">
      <SideTag side={side} className="mt-[-3px]" />
      {data.sentiment ? <ShareBar value={value} tone={tone} label={`${label}, side ${side.toUpperCase()}`} />
        : <p className="text-[13px] text-ink-3">{notMeasurableReason(data)}</p>}
    </div>
  )
}

/** Share of analysed reviews per tone, for both sides, with 95% intervals and the separation label. */
export function SentimentCompare({ comparison }) {
  const { a, b, sentiment } = comparison
  return (
    <Panel title="Tone of the reviews"
      description="Share of analysed reviews that read as positive, neutral or negative. The dark line on each bar is its 95% interval.">
      <div className="space-y-5">
        {TONES.map(({ key, label }) => {
          const row = sentiment?.[key]
          return (
            <div key={key} className="border-t border-line pt-4 first:border-t-0 first:pt-0">
              <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
                <h3 className="text-[13px] font-semibold text-ink">{label}</h3>
                <SeparationBadge value={row?.separation ?? 'not-measurable'} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2 sm:gap-6">
                <SideShare side="a" data={a} value={a.sentiment?.[key]} tone={key} label={label} />
                <SideShare side="b" data={b} value={b.sentiment?.[key]} tone={key} label={label} />
              </div>
              {row?.difference != null && <p className="mt-2 text-xs text-ink-3">{differenceText(row.difference, 'percentage points')}</p>}
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

function RatingSide({ side, data }) {
  const { ratings, product } = data
  return (
    <div className="min-w-0">
      <div className="flex items-center gap-2.5">
        <SideTag side={side} />
        <p className="truncate text-[13px] font-semibold text-ink" title={product.name}>{product.name}</p>
      </div>
      {ratings.rated ? (
        <>
          <div className="mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-2xl font-semibold text-ink tabular-nums">{formatRating(ratings.average)}</span>
            <Stars value={Math.round(ratings.average)} />
            <span className="text-[13px] text-ink-3">from {plural(ratings.rated, 'rated review')}</span>
          </div>
          <ul className="mt-3 space-y-1.5" aria-label={`Star ratings, side ${side.toUpperCase()}`}>
            {ratings.distribution.map((row) => (
              <li key={row.stars} className="grid grid-cols-[2rem_minmax(0,1fr)_7.5rem] items-center gap-2 text-[13px]">
                <span className="text-ink-2 tabular-nums">{row.stars}★</span>
                <div className="h-2.5 rounded-sm bg-subtle" aria-hidden>
                  <div className="h-full rounded-sm bg-[#c98a12]" style={{ width: `${row.percent ?? 0}%` }} />
                </div>
                <span className="text-right text-ink-3 tabular-nums">{formatPercent(row.percent)} ({row.count.toLocaleString('en-IN')})</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-3 text-[13px] text-ink-3">No star ratings in this run.</p>
      )}
      {ratings.storeRating != null && (
        <p className="mt-3 text-xs text-ink-3">
          Store’s own rating, not part of this analysis: {formatRating(ratings.storeRating)}
          {ratings.storeRatingCount ? ` from ${plural(ratings.storeRatingCount, 'rating')}` : ''}.
        </p>
      )}
    </div>
  )
}

/** Average star rating and distribution per side (as shares of rated reviews, so sizes don't distort it). */
export function RatingCompare({ comparison }) {
  return (
    <Panel title="Star ratings" description="Shares of each side’s rated reviews. Star ratings are measured separately from the tone of the text.">
      <div className="grid gap-6 md:grid-cols-2 md:gap-8">
        <RatingSide side="a" data={comparison.a} />
        <RatingSide side="b" data={comparison.b} />
      </div>
    </Panel>
  )
}

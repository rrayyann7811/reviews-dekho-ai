import { formatPercent, formatRating, plural } from '../../lib/format'

function Stat({ label, value, detail, swatch }) {
  return (
    <div className="bg-surface px-5 py-4 first:col-span-2 xl:first:col-span-1">
      <dt className="flex items-center gap-2 text-[13px] text-ink-3">
        {swatch && <span aria-hidden className={`size-2 rounded-full ${swatch}`} />}
        {label}
      </dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight tabular-nums text-ink">{value}</dd>
      <dd className="mt-0.5 text-xs text-ink-3">{detail}</dd>
    </div>
  )
}

export default function StatStrip({ stats, ingestion }) {
  const { totalReviews, sentimentCounts: c, sentimentPercent: p } = stats
  const analysed = stats.analysedReviews ?? totalReviews // runs before Phase 4 analysed every review
  const notEnglish = totalReviews - analysed
  const skippedParts = [
    ingestion?.duplicatesRemoved && plural(ingestion.duplicatesRemoved, 'duplicate'),
    ingestion?.emptyRemoved && plural(ingestion.emptyRemoved, 'empty row'),
  ].filter(Boolean)
  const detail = [
    notEnglish > 0 && `${notEnglish} of ${totalReviews} not in English`,
    skippedParts.length ? `Skipped ${skippedParts.join(' and ')}` : !notEnglish && 'No rows skipped',
  ].filter(Boolean).join(' · ')
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line xl:grid-cols-5">
      <Stat label="Reviews analysed" value={analysed} detail={detail} />
      <Stat label="Average rating" value={stats.averageRating ? `${formatRating(stats.averageRating)} / 5` : '—'}
        detail={stats.ratedReviews ? `From ${plural(stats.ratedReviews, 'rated review')}` : 'No star ratings in data'} />
      {/* With nothing analysed a percentage would be a misleading 0%, so show "—" instead. */}
      <Stat label="Positive" swatch="bg-pos" value={analysed ? formatPercent(p.positive) : '—'} detail={analysed ? plural(c.positive, 'review') : 'Not measurable'} />
      <Stat label="Neutral" swatch="bg-neu" value={analysed ? formatPercent(p.neutral) : '—'} detail={analysed ? plural(c.neutral, 'review') : 'Not measurable'} />
      <Stat label="Negative" swatch="bg-neg" value={analysed ? formatPercent(p.negative) : '—'} detail={analysed ? plural(c.negative, 'review') : 'Not measurable'} />
    </dl>
  )
}

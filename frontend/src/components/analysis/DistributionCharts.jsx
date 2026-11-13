import { formatPercent, plural } from '../../lib/format'
import { SENTIMENTS } from '../../lib/theme'
import HBarChart from '../charts/HBarChart'
import Panel from '../ui/Panel'

export default function DistributionCharts({ stats, onShowMismatches }) {
  const total = stats.totalReviews
  const sentimentData = SENTIMENTS.map((s) => ({
    label: s.label,
    value: stats.sentimentCounts[s.key],
    percent: stats.sentimentPercent[s.key],
    color: s.color,
  }))
  const ratingData = stats.ratingDistribution.map((r) => ({
    label: `${r.stars} star${r.stars === 1 ? '' : 's'}`,
    value: r.count,
    percent: stats.ratedReviews ? (100 * r.count) / stats.ratedReviews : 0,
  }))
  const mismatches = stats.ratingSentimentMismatches.length

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Panel title="Tone of the review text" description={`How the wording of all ${total} reviews reads.`}>
        <HBarChart
          data={sentimentData}
          ariaLabel={sentimentData.map((d) => `${d.label}: ${d.value} reviews`).join(', ')}
          valueLabel={(d) => `${d.value} · ${formatPercent(d.percent)}`}
          describe={(d) => `${plural(d.value, 'review')}, ${formatPercent(d.percent)} of ${total}`}
        />
        <p className="mt-3 border-t border-line pt-3 text-[13px] text-ink-3">
          Each review gets a score from −1 (very negative) to +1 (very positive). Scores between −0.05 and +0.05 count as neutral.
        </p>
      </Panel>
      <Panel title="Star ratings" description={stats.ratedReviews ? `${stats.ratedReviews} of ${total} reviews include a star rating.` : 'This data has no star ratings.'}>
        {stats.ratedReviews ? (
          <HBarChart
            data={ratingData}
            rowHeight={28}
            ariaLabel={ratingData.map((d) => `${d.label}: ${d.value} reviews`).join(', ')}
            valueLabel={(d) => `${d.value} · ${formatPercent(d.percent)}`}
            describe={(d) => `${plural(d.value, 'review')}, ${formatPercent(d.percent)} of rated reviews`}
          />
        ) : (
          <p className="text-[13px] text-ink-3">Sentiment is still measured from the text.</p>
        )}
        {mismatches > 0 && (
          <p className="mt-3 border-t border-line pt-3 text-[13px] text-ink-3">
            {plural(mismatches, 'review')} {mismatches === 1 ? 'has' : 'have'} a star rating that disagrees with its wording.{' '}
            <button type="button" onClick={onShowMismatches} className="font-medium text-brand-600 hover:underline">Show {mismatches === 1 ? 'it' : 'them'}</button>
          </p>
        )}
      </Panel>
    </div>
  )
}

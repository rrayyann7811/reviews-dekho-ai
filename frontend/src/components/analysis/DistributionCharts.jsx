import { describeEngine } from '../../lib/engine'
import { formatPercent, plural } from '../../lib/format'
import { SENTIMENTS } from '../../lib/theme'
import HBarChart from '../charts/HBarChart'
import SplitBar from '../charts/SplitBar'
import Panel from '../ui/Panel'

/** For each star rating, how the wording of those reviews reads. Shows whether stars and text agree. */
function ToneByRating({ rows }) {
  const rated = rows.filter((r) => r.reviews > 0)
  return (
    <Panel title="Tone of the text by star rating" className="lg:col-span-2"
      description="For reviews with each star rating, how their wording reads. Stars and text are measured separately.">
      {/* Phones: rating and counts on one line, the bar full width below. Wider screens: one row. */}
      <ul className="space-y-2.5 text-[13px] sm:space-y-1.5">
        {rated.map((r) => (
          <li key={r.stars} className="grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-1 sm:grid-cols-[4.5rem_1fr_auto]">
            <span className="font-medium whitespace-nowrap text-ink-2">{r.stars} star{r.stars === 1 ? '' : 's'}</span>
            <span className="text-right text-ink-3 tabular-nums sm:order-3 sm:whitespace-nowrap">
              <span className="sr-only">Positive / neutral / negative: </span>
              {r.positive} / {r.neutral} / {r.negative}
              {r.notAnalysed > 0 && <span className="ml-1.5">· {r.notAnalysed} not analysed</span>}
            </span>
            <div className="col-span-2 sm:order-2 sm:col-span-1">
              <SplitBar positive={r.positive} neutral={r.neutral} negative={r.negative}
                label={`${r.stars} stars: ${r.positive} positive, ${r.neutral} neutral, ${r.negative} negative`} />
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  )
}

export default function DistributionCharts({ stats, engine, toneByRating = [], onShowMismatches }) {
  const total = stats.totalReviews
  const analysed = stats.analysedReviews ?? total
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
      <Panel title="Tone of the review text"
        description={analysed === total
          ? `How the wording of all ${total} reviews reads.`
          : analysed === 0
            ? 'How the wording of the reviews reads.'
            : `How the wording of the ${analysed} English reviews reads. ${total - analysed} not in English ${total - analysed === 1 ? 'is' : 'are'} not analysed.`}>
        {analysed > 0 ? (
          <HBarChart
            data={sentimentData}
            ariaLabel={sentimentData.map((d) => `${d.label}: ${d.value} reviews`).join(', ')}
            valueLabel={(d) => `${d.value} · ${formatPercent(d.percent)}`}
            describe={(d) => `${plural(d.value, 'review')}, ${formatPercent(d.percent)} of ${analysed}`}
          />
        ) : (
          <p className="text-[13px] text-ink-3">
            None of the {plural(total, 'review')} could be analysed for tone, because none is in English. Star ratings are still shown.
          </p>
        )}
        <p className="mt-3 border-t border-line pt-3 text-[13px] text-ink-3">
          {describeEngine(engine).scoreNote}
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
      {stats.ratedReviews > 0 && toneByRating.some((r) => r.reviews > 0) && <ToneByRating rows={toneByRating} />}
    </div>
  )
}

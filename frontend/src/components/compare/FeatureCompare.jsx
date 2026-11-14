import { formatPercent } from '../../lib/format'
import SplitBar from '../charts/SplitBar'
import Alert from '../ui/Alert'
import { SentimentBadge } from '../ui/Badge'
import EmptyState from '../ui/EmptyState'
import Panel from '../ui/Panel'
import { FEATURE_STATUS, FEATURE_STATUS_HELP } from '../../lib/compareText'
import { SeparationBadge, SideTag } from './parts'

/** One side of one feature: its split and counts, or why there is nothing to compare. */
function FeatureSide({ aspect, side, value }) {
  const label = `${aspect}, side ${side.toUpperCase()}`
  if (value.status === 'compared' || value.status === 'few-mentions') {
    return (
      <div className="min-w-0 space-y-1.5">
        <SplitBar positive={value.positive} neutral={value.neutral} negative={value.negative}
          label={`${label}: ${value.positive} positive, ${value.neutral} neutral, ${value.negative} negative mentions`} />
        <p className="text-xs text-ink-2 tabular-nums">
          {value.positive} / {value.neutral} / {value.negative}
          <span className="text-ink-3"> · {value.mentions} {value.mentions === 1 ? 'mention' : 'mentions'}
            {value.mentionRate && <> · {formatPercent(value.mentionRate.percent)} of analysed reviews</>}</span>
        </p>
        {value.status === 'compared'
          ? <SentimentBadge value={value.verdict} />
          : <p className="text-xs text-ink-3">{FEATURE_STATUS['few-mentions']}</p>}
      </div>
    )
  }
  return <p className="min-w-0 text-[13px] text-ink-3">{FEATURE_STATUS[value.status]}</p>
}

const LOOKED_FOR = (status) => status !== 'not-looked-for' && status !== 'unknown'

/** Why a row isn't compared, in the order a reader would check it. */
function notComparedReason(row) {
  const statuses = [row.a.status, row.b.status]
  if (statuses.includes('not-looked-for')) return 'Not compared: this feature wasn’t looked for on one side.'
  if (statuses.includes('unknown')) return 'Not compared: an older run didn’t record whether it looked for this feature.'
  return 'Not compared: needs at least 3 mentions on both sides.'
}

/** Explains each status that appears, once, instead of in every cell. */
function Legend({ features }) {
  const present = new Set(features.flatMap((r) => [r.a.status, r.b.status]))
  const shown = Object.keys(FEATURE_STATUS_HELP).filter((s) => present.has(s))
  if (!shown.length) return null
  return (
    <dl className="grid gap-x-6 gap-y-1.5 border-b border-line px-5 py-3 text-xs sm:grid-cols-2">
      {shown.map((s) => (
        <div key={s}>
          <dt className="inline font-medium text-ink-2">{FEATURE_STATUS[s]}: </dt>
          <dd className="inline text-ink-3">{FEATURE_STATUS_HELP[s]}</dd>
        </div>
      ))}
    </dl>
  )
}

function Differences({ row }) {
  if (!row.comparable) {
    return <p className="text-xs text-ink-3">{notComparedReason(row)}</p>
  }
  const items = [
    ['Positive share of mentions', row.tone.positive],
    ['Negative share of mentions', row.tone.negative],
    ['Share of reviews mentioning it', row.mentionRate],
  ]
  return (
    <dl className="space-y-1.5">
      {items.map(([label, value]) => (
        <div key={label} className="flex flex-col gap-0.5">
          <dt className="text-xs text-ink-3">
            {label}: <span className="text-ink-2 tabular-nums">A {formatPercent(value.a.percent)} · B {formatPercent(value.b.percent)}</span>
          </dt>
          <dd><SeparationBadge value={value.separation} /></dd>
        </div>
      ))}
    </dl>
  )
}

export function FeatureCompare({ features }) {
  const comparable = features.filter((r) => r.comparable).length
  const lookedForOnBoth = features.some((r) => LOOKED_FOR(r.a.status) && LOOKED_FOR(r.b.status))
  return (
    <Panel title="Features"
      description="Positive / neutral / negative mentions per side. Features are compared by shares, never by raw counts, and missing features are never counted as negative."
      bodyClassName="">
      {features.length === 0 ? (
        <EmptyState title="No features were mentioned on either side" />
      ) : (
        <>
          {comparable === 0 && (
            <div className="p-5 pb-0">
              <Alert>
                {lookedForOnBoth
                  ? 'No feature has at least 3 mentions on both sides, so no feature is compared.'
                  : 'The two sides weren’t checked for any of the same features (for example, an app and a physical product), so no feature can be compared.'}
                {' '}Each side’s figures are shown for reference.
              </Alert>
            </div>
          )}
          <Legend features={features} />
          {/* Desktop: a table */}
          <div className="hidden lg:block">
            <table className="w-full table-fixed text-left text-sm">
              <caption className="sr-only">Feature comparison between side A and side B</caption>
              <thead className="bg-subtle text-xs text-ink-3">
                <tr>
                  <th scope="col" className="w-[16%] px-5 py-2.5 font-medium">Feature</th>
                  <th scope="col" className="w-[28%] px-3 py-2.5 font-medium"><span className="inline-flex items-center gap-1.5"><SideTag side="a" /> Side A</span></th>
                  <th scope="col" className="w-[28%] px-3 py-2.5 font-medium"><span className="inline-flex items-center gap-1.5"><SideTag side="b" /> Side B</span></th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Comparison</th>
                </tr>
              </thead>
              <tbody>
                {features.map((row) => (
                  <tr key={row.aspect} className="border-t border-line align-top">
                    <th scope="row" className="px-5 py-3.5 font-medium break-words text-ink">{row.aspect}</th>
                    <td className="px-3 py-3.5"><FeatureSide aspect={row.aspect} side="a" value={row.a} /></td>
                    <td className="px-3 py-3.5"><FeatureSide aspect={row.aspect} side="b" value={row.b} /></td>
                    <td className="px-5 py-3.5"><Differences row={row} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Phones and tablets: one card per feature */}
          <ul className="divide-y divide-line lg:hidden" aria-label="Feature comparison">
            {features.map((row) => (
              <li key={row.aspect} className="space-y-3 p-5">
                <h3 className="text-sm font-semibold break-words text-ink">{row.aspect}</h3>
                <div className="grid gap-3 sm:grid-cols-2">
                  {['a', 'b'].map((side) => (
                    <div key={side} className="grid grid-cols-[1.25rem_minmax(0,1fr)] gap-2.5">
                      <SideTag side={side} />
                      <FeatureSide aspect={row.aspect} side={side} value={row[side]} />
                    </div>
                  ))}
                </div>
                <Differences row={row} />
              </li>
            ))}
          </ul>
        </>
      )}
    </Panel>
  )
}

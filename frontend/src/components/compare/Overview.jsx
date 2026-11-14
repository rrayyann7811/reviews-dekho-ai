import { Link } from 'react-router-dom'
import { formatDate, formatRating, plural } from '../../lib/format'
import Alert from '../ui/Alert'
import { SourceBadge } from '../ui/Badge'
import Panel from '../ui/Panel'
import { SideTag } from './parts'

const REASONS = { languageNotSupported: 'not in English' }

function engineName(engine) {
  return engine.pipelineVersion >= 2 ? engine.name : `${engine.name} (earlier pipeline)`
}

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-4 border-t border-line py-2 first:border-t-0">
      <dt className="text-ink-3">{label}</dt>
      <dd className="min-w-0 text-right text-ink">{children}</dd>
    </div>
  )
}

/** Product, run and sample of one side. */
export function SideCard({ side, data }) {
  const { product, run, engine, counts, dateRange, ratings } = data
  const reasons = Object.entries(counts.notAnalysedReasons ?? {})
    .map(([key, n]) => `${n.toLocaleString('en-IN')} ${REASONS[key] ?? key}`).join(', ')
  return (
    <section aria-label={`Side ${side.toUpperCase()}: ${product.name}`} className="rounded-lg border border-line bg-surface p-5">
      <div className="flex items-start gap-2.5">
        <SideTag side={side} className="mt-0.5" />
        <div className="min-w-0">
          <h2 className="text-sm font-semibold break-words text-ink">
            <Link to={`/products/${product.id}`} className="hover:underline">{product.name}</Link>
          </h2>
          <p className="mt-0.5 text-[13px] text-ink-3">
            Run #{run.id} · {formatDate(run.createdAt)} ·{' '}
            {run.isLatest ? 'latest run' : `earlier run (latest is #${run.latestRunId})`}
          </p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <SourceBadge source={product.source} />
        {product.sourceSiteName && (
          <span className="text-xs text-ink-3">
            {product.sourceSiteName}{product.sourceRegion ? ` · ${product.sourceRegion.toUpperCase()} store` : ''}
          </span>
        )}
        <span className="text-xs text-ink-3">{product.domain === 'app' ? 'App' : 'Physical product'}</span>
      </div>
      <dl className="mt-3 text-[13px]">
        <Row label="Analysed reviews">
          <span className="font-semibold tabular-nums">{counts.analysed.toLocaleString('en-IN')}</span>
          <span className="text-ink-3"> of {counts.total.toLocaleString('en-IN')}</span>
        </Row>
        <Row label="Not analysed">
          <span className="tabular-nums">{counts.notAnalysed.toLocaleString('en-IN')}</span>
          {reasons && <span className="text-ink-3"> ({reasons})</span>}
        </Row>
        <Row label="Star ratings">
          {ratings.rated ? `${formatRating(ratings.average)} average from ${plural(ratings.rated, 'rated review')}` : 'None'}
        </Row>
        <Row label="Review period">
          {dateRange?.from ? `${formatDate(dateRange.from)} – ${formatDate(dateRange.to)}` : 'No dates'}
        </Row>
        <Row label="Sentiment method">{engineName(engine)}</Row>
      </dl>
    </section>
  )
}

/** Caveats first: warnings, then information. */
export function CaveatList({ caveats }) {
  if (!caveats.length) return null
  const sorted = [...caveats].sort((x, y) => (x.severity === y.severity ? 0 : x.severity === 'warning' ? -1 : 1))
  const warnings = sorted.filter((c) => c.severity === 'warning').length
  return (
    <section aria-labelledby="caveats-title" className="space-y-2">
      <h2 id="caveats-title" className="text-sm font-semibold text-ink">
        Read before comparing{warnings > 0 && <span className="font-normal text-ink-3"> · {plural(warnings, 'warning')}</span>}
      </h2>
      {sorted.map((c) => (
        <Alert key={`${c.code}-${c.message}`} variant={c.severity === 'warning' ? 'warning' : 'info'}>
          <span className="sr-only">{c.severity === 'warning' ? 'Warning: ' : 'Note: '}</span>{c.message}
        </Alert>
      ))}
    </section>
  )
}

/** The deterministic comparison statements and the notes on what "clear separation" means. */
export function Statements({ statements, notes }) {
  return (
    <Panel title="What the figures show" description="Built only from the figures on this page; no AI is used.">
      <ul className="space-y-2 text-sm text-ink">
        {statements.map((s) => (
          <li key={s} className="flex gap-2"><span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-ink-3" />{s}</li>
        ))}
      </ul>
      <div className="mt-4 space-y-1 border-t border-line pt-3 text-[13px] text-ink-3">
        {notes.map((n) => <p key={n}>{n}</p>)}
      </div>
    </Panel>
  )
}

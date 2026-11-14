// Small building blocks of the comparison page. Every figure is printed as text; bars only repeat it.
import { CheckCircle2, CircleSlash, Equal, Users } from 'lucide-react'
import { intervalText } from '../../lib/compareText'
import { formatPercent } from '../../lib/format'

const SIDE_STYLE = {
  a: 'bg-brand-600 text-white',
  b: 'bg-ink text-surface',
}

/** "A" / "B" marker. The letter carries the meaning; the colour only helps scanning. */
export function SideTag({ side, className = '' }) {
  return (
    <span aria-hidden className={`inline-flex size-5 shrink-0 items-center justify-center rounded text-[11px] font-semibold ${SIDE_STYLE[side]} ${className}`}>
      {side.toUpperCase()}
    </span>
  )
}

const FILL = { positive: 'bg-pos', neutral: 'bg-neu', negative: 'bg-neg', brand: 'bg-brand-600' }

/** A share as a bar with its 95% interval drawn as a line, plus the same figures as text. */
export function ShareBar({ value, tone = 'brand', label, detail = true }) {
  if (!value || value.percent == null) {
    return <p className="text-[13px] text-ink-3">Not measurable (no analysed reviews)</p>
  }
  const [low, high] = value.interval ?? [value.percent, value.percent]
  return (
    <div className="min-w-0">
      <div className="relative h-2.5 w-full rounded-sm bg-subtle" role="img"
        aria-label={`${label ? `${label}: ` : ''}${formatPercent(value.percent)}, ${value.count} of ${value.n}${value.interval ? `, ${intervalText(value.interval)}` : ''}`}>
        <div className={`h-full rounded-sm ${FILL[tone]}`} style={{ width: `${value.percent}%` }} />
        {value.interval && (
          <div aria-hidden className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-ink/70"
            style={{ left: `${low}%`, width: `${Math.max(high - low, 0.6)}%` }} />
        )}
      </div>
      <p className="mt-1 text-[13px] text-ink-2 tabular-nums">
        <span className="font-semibold text-ink">{formatPercent(value.percent)}</span>
        {detail && (
          <span className="text-ink-3"> · {value.count.toLocaleString('en-IN')} of {value.n.toLocaleString('en-IN')}
            {value.interval && <> · <span className="whitespace-nowrap">{intervalText(value.interval)}</span></>}</span>
        )}
      </p>
    </div>
  )
}

const SEPARATION = {
  clear: { text: 'Clear separation in these samples', icon: CheckCircle2, className: 'bg-brand-50 text-brand-700' },
  overlapping: { text: 'Intervals overlap', icon: Equal, className: 'bg-neu-soft text-neu-ink' },
  'too-few': { text: 'Too few to compare', icon: Users, className: 'bg-neu-soft text-neu-ink' },
  'not-measurable': { text: 'Not measurable', icon: CircleSlash, className: 'border border-dashed border-line-strong text-ink-3' },
}

export function SeparationBadge({ value }) {
  const config = SEPARATION[value] ?? SEPARATION['not-measurable']
  const Icon = config.icon
  return (
    <span className={`inline-flex min-h-6 items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ${config.className}`}>
      <Icon aria-hidden className="size-3.5 shrink-0" />
      {config.text}
    </span>
  )
}

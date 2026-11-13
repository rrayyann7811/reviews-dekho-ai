import { FileSpreadsheet, FlaskConical, Link2 } from 'lucide-react'

const tone = {
  positive: 'bg-pos-soft text-pos',
  neutral: 'bg-neu-soft text-neu-ink',
  negative: 'bg-neg-soft text-neg',
  mixed: 'bg-mix-soft text-mix',
  insufficient: 'bg-neu-soft text-neu-ink',
  brand: 'bg-brand-50 text-brand-700',
}

const dot = {
  positive: 'bg-pos',
  neutral: 'bg-neu',
  negative: 'bg-neg',
  mixed: 'bg-mix',
  insufficient: 'bg-neu',
}

export function Badge({ variant = 'neutral', children, className = '' }) {
  return (
    <span className={`inline-flex h-6 items-center gap-1.5 rounded-md px-2 text-xs font-medium whitespace-nowrap ${tone[variant]} ${className}`}>
      {children}
    </span>
  )
}

const SENTIMENT_LABEL = {
  positive: 'Positive',
  neutral: 'Neutral',
  negative: 'Negative',
  mixed: 'Mixed',
  insufficient: 'Too few mentions',
}

export function SentimentBadge({ value }) {
  return (
    <Badge variant={value}>
      <span aria-hidden className={`size-1.5 rounded-full ${dot[value]}`} />
      {SENTIMENT_LABEL[value] ?? value}
    </Badge>
  )
}

const SOURCES = {
  demo: { label: 'Demo data', icon: FlaskConical, className: 'border-mix/30 bg-mix-soft text-mix' },
  upload: { label: 'Uploaded file', icon: FileSpreadsheet, className: 'border-line-strong bg-surface text-ink-2' },
  url: { label: 'Product link', icon: Link2, className: 'border-line-strong bg-surface text-ink-2' },
}

export function SourceBadge({ source }) {
  const config = SOURCES[source] ?? SOURCES.upload
  const Icon = config.icon
  return (
    <span className={`inline-flex h-6 items-center gap-1.5 rounded-md border px-2 text-xs font-medium whitespace-nowrap ${config.className}`}>
      <Icon aria-hidden className="size-3.5" />
      {config.label}
    </span>
  )
}

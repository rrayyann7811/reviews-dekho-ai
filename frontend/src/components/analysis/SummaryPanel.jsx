import Panel from '../ui/Panel'

/** Up to three exact excerpts that support a claim (summary version 2), or the single example (version 1). */
function Evidence({ item, onOpenReview }) {
  const excerpts = item.evidence ?? (item.example ? [item.example] : [])
  if (!excerpts.length) return null
  return (
    <ul className="mt-1.5 space-y-1.5">
      {excerpts.map((e) => (
        <li key={e.reviewId}>
          <blockquote className="border-l-2 border-line-strong pl-2.5 text-[13px] text-ink-2">
            “{e.text}”{' '}
            <button type="button" onClick={() => onOpenReview(e.reviewId)} className="text-xs whitespace-nowrap text-brand-600 hover:underline">
              Read review
            </button>
          </blockquote>
        </li>
      ))}
    </ul>
  )
}

function AspectList({ title, items, tone, emptyText, onOpenReview }) {
  return (
    <div className="px-5 py-4">
      <h3 className="flex items-center gap-2 text-[13px] font-semibold text-ink">
        <span aria-hidden className={`size-2 rounded-full ${tone}`} />
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="mt-2 text-[13px] text-ink-3">{emptyText}</p>
      ) : (
        <ul className="mt-3 space-y-4">
          {items.map((item) => (
            <li key={item.aspect}>
              <p className="text-sm font-medium text-ink">{item.aspect}</p>
              <p className="text-xs text-ink-3 tabular-nums">{item.detail}</p>
              <Evidence item={item} onOpenReview={onOpenReview} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export default function SummaryPanel({ summary, onOpenReview }) {
  // Version 2 summaries count analysed reviews that mention a feature; version 1 used the same numbers.
  const strengths = summary.strengths.map((s) => ({ ...s, detail: `${s.count} of ${s.mentions} reviews that mention it are positive (${s.percent}%)` }))
  const complaints = summary.complaints.map((s) => ({ ...s, detail: `${s.count} of ${s.mentions} reviews that mention it are negative (${s.percent}%)` }))
  const mixed = summary.mixed.map((s) => ({ ...s, detail: `Of ${s.mentions} reviews that mention it: ${s.positive} positive, ${s.neutral} neutral, ${s.negative} negative` }))

  return (
    <Panel title="Summary" description="Written from the stored analysis results, with exact excerpts from the reviews. No AI model is used." bodyClassName="">
      {summary.overview ? (
        <p className="border-b border-line px-5 py-4 text-sm leading-relaxed text-ink">{summary.overview}</p>
      ) : null}
      <div className="grid divide-y divide-line md:grid-cols-3 md:divide-x md:divide-y-0">
        <AspectList title="What customers like" tone="bg-pos" items={strengths} onOpenReview={onOpenReview}
          emptyText="No feature is clearly praised by most of the reviews that mention it." />
        <AspectList title="Common complaints" tone="bg-neg" items={complaints} onOpenReview={onOpenReview}
          emptyText="No feature is criticised by most of the reviews that mention it." />
        <AspectList title="Mixed opinions" tone="bg-mix" items={mixed} onOpenReview={onOpenReview}
          emptyText="No features with clearly divided opinions." />
      </div>
      {summary.notes.length > 0 && (
        <ul className="space-y-1 border-t border-line bg-subtle px-5 py-3 text-[13px] text-ink-3">
          {summary.notes.map((n) => <li key={n}>{n}</li>)}
        </ul>
      )}
    </Panel>
  )
}

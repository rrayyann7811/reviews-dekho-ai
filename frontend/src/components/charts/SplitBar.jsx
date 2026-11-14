/** A bar split into positive / neutral / negative parts. Used for features and for tone by star rating. */
export default function SplitBar({ positive, neutral, negative, total = positive + neutral + negative, label }) {
  const parts = [
    { key: 'positive', value: positive, className: 'bg-pos' },
    { key: 'neutral', value: neutral, className: 'bg-neu' },
    { key: 'negative', value: negative, className: 'bg-neg' },
  ].filter((p) => p.value > 0)
  return (
    <div className="flex h-2.5 w-full min-w-[120px] gap-0.5 overflow-hidden rounded-sm bg-subtle" role="img"
      aria-label={label ?? `${positive} positive, ${neutral} neutral, ${negative} negative`}
      title={`${positive} positive, ${neutral} neutral, ${negative} negative`}>
      {total > 0 && parts.map((p) => <div key={p.key} className={p.className} style={{ width: `${(100 * p.value) / total}%` }} />)}
    </div>
  )
}

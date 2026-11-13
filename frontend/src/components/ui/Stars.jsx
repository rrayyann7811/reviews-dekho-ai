import { Star } from 'lucide-react'

/** Read-only star rating. Shows "No rating" when the value is missing. */
export default function Stars({ value, size = 'size-3.5' }) {
  if (value === null || value === undefined) return <span className="text-xs text-ink-3">No rating</span>
  return (
    <span className="inline-flex items-center gap-0.5" role="img" aria-label={`${value} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} aria-hidden className={`${size} ${n <= value ? 'fill-[#c98a12] text-[#c98a12]' : 'fill-line text-line'}`} />
      ))}
    </span>
  )
}

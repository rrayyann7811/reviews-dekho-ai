import { LoaderCircle } from 'lucide-react'

export default function Spinner({ label = 'Loading…', className = '' }) {
  return (
    <span role="status" className={`inline-flex items-center gap-2 text-[13px] text-ink-3 ${className}`}>
      <LoaderCircle aria-hidden className="size-4 animate-spin" />
      {label}
    </span>
  )
}

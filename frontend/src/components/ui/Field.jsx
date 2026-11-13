import { useId } from 'react'

const control =
  'h-9 w-full rounded-md border bg-surface px-3 text-sm text-ink placeholder:text-ink-3 transition-colors focus:outline-none focus:ring-3 disabled:bg-subtle'
const ok = 'border-line-strong focus:border-brand-600 focus:ring-brand-100'
const bad = 'border-neg focus:border-neg focus:ring-neg-soft'

/** Label + control + hint/error, wired together for screen readers. */
export function Field({ label, hint, error, children, className = '', hideLabel = false }) {
  const id = useId()
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={className}>
      <label htmlFor={id} className={hideLabel ? 'sr-only' : 'mb-1.5 block text-[13px] font-medium text-ink'}>
        {label}
      </label>
      {children({ id, 'aria-describedby': describedBy, 'aria-invalid': error ? true : undefined })}
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-[13px] text-neg">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1.5 text-[13px] text-ink-3">{hint}</p>
      ) : null}
    </div>
  )
}

export function Input({ invalid, className = '', ...props }) {
  return <input className={`${control} ${invalid ? bad : ok} ${className}`} {...props} />
}

export function Select({ className = '', children, ...props }) {
  return (
    <select className={`${control} ${ok} cursor-pointer pr-8 ${className}`} {...props}>
      {children}
    </select>
  )
}

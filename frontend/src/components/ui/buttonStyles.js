const base =
  'inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50'

const variants = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 disabled:hover:bg-brand-600',
  secondary: 'border border-line-strong bg-surface text-ink hover:bg-subtle',
  ghost: 'text-ink-2 hover:bg-black/[0.04] hover:text-ink',
}

const sizes = {
  sm: 'h-8 px-3 text-[13px]',
  md: 'h-9 px-3.5 text-sm',
}

export function buttonClasses({ variant = 'primary', size = 'md', className = '' } = {}) {
  return `${base} ${variants[variant]} ${sizes[size]} ${className}`
}

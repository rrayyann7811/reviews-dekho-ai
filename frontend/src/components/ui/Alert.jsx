import { AlertCircle, AlertTriangle, Info } from 'lucide-react'

const styles = {
  info: { box: 'border-brand-100 bg-brand-50', icon: Info, iconColor: 'text-brand-600' },
  warning: { box: 'border-mix/25 bg-mix-soft', icon: AlertTriangle, iconColor: 'text-mix' },
  error: { box: 'border-neg/25 bg-neg-soft', icon: AlertCircle, iconColor: 'text-neg' },
}

export default function Alert({ variant = 'info', title, children, action, className = '' }) {
  const style = styles[variant]
  const Icon = style.icon
  return (
    <div role={variant === 'error' ? 'alert' : 'status'} className={`flex gap-3 rounded-lg border px-4 py-3 ${style.box} ${className}`}>
      <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${style.iconColor}`} />
      <div className="min-w-0 flex-1 text-[13px] text-ink-2">
        {title && <p className="font-medium text-ink">{title}</p>}
        {children && <div className={title ? 'mt-0.5' : ''}>{children}</div>}
        {action && <div className="mt-2.5">{action}</div>}
      </div>
    </div>
  )
}

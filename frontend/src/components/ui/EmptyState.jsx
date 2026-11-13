export default function EmptyState({ icon: Icon, title, children, action, className = '' }) {
  return (
    <div className={`flex flex-col items-center px-6 py-12 text-center ${className}`}>
      {Icon && (
        <div className="mb-3 flex size-10 items-center justify-center rounded-lg border border-line bg-subtle">
          <Icon aria-hidden className="size-5 text-ink-3" />
        </div>
      )}
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 max-w-sm text-[13px] text-ink-3">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

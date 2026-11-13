export default function Panel({ title, description, actions, children, className = '', bodyClassName = 'p-5', as: Tag = 'section' }) {
  return (
    <Tag className={`rounded-lg border border-line bg-surface ${className}`}>
      {(title || actions) && (
        <header className={`flex flex-wrap justify-between gap-3 border-b border-line px-5 py-3.5 ${description ? 'items-start' : 'items-center'}`}>
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-[13px] text-ink-3">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClassName}>{children}</div>
    </Tag>
  )
}

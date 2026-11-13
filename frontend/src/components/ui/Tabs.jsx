/** Simple accessible tab list; the parent owns which tab is active. */
export default function Tabs({ tabs, value, onChange, label }) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => {
        const active = tab.value === value
        return (
          <button
            key={tab.value}
            role="tab"
            type="button"
            id={`tab-${tab.value}`}
            aria-selected={active}
            aria-controls={`panel-${tab.value}`}
            onClick={() => onChange(tab.value)}
            className={`-mb-px flex h-10 items-center gap-2 border-b-2 px-3 text-sm whitespace-nowrap transition-colors ${
              active ? 'border-brand-600 font-medium text-ink' : 'border-transparent text-ink-3 hover:text-ink'
            }`}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className={`rounded px-1.5 text-xs tabular-nums ${active ? 'bg-brand-50 text-brand-700' : 'bg-neu-soft text-ink-3'}`}>
                {tab.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

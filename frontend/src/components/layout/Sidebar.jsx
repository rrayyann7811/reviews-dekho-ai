import { Columns2, FileDown, History, LayoutGrid, Link2, Settings, Upload } from 'lucide-react'
import { NavLink } from 'react-router-dom'
import { useServerStatus } from '../../lib/serverStatus'
import Logo from './Logo'

const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: LayoutGrid, end: true },
  { to: '/analyze', label: 'Analyze product', icon: Link2 },
  { to: '/upload', label: 'Upload reviews', icon: Upload },
  { to: '/history', label: 'Analysis history', icon: History },
  { to: '/compare', label: 'Compare products', icon: Columns2 },
  { to: '/reports', label: 'Reports', icon: FileDown },
]

function NavItem({ to, label, icon: Icon, end, onNavigate }) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onNavigate}
      className={({ isActive }) =>
        `flex h-9 items-center gap-3 rounded-md px-2.5 text-sm transition-colors ${
          isActive ? 'bg-brand-50 font-medium text-brand-700' : 'text-ink-2 hover:bg-black/[0.04] hover:text-ink'
        }`
      }
    >
      <Icon aria-hidden className="size-4 shrink-0" />
      {label}
    </NavLink>
  )
}

const STATUS = {
  online: { dot: 'bg-pos', text: 'Server connected' },
  offline: { dot: 'bg-neg', text: 'Server offline' },
  checking: { dot: 'bg-neu', text: 'Checking server…' },
}

export default function Sidebar({ onNavigate }) {
  const { status } = useServerStatus()
  const s = STATUS[status]
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center px-4">
        <Logo />
      </div>
      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-2">
        <ul className="space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <NavItem {...item} onNavigate={onNavigate} />
            </li>
          ))}
        </ul>
      </nav>
      <div className="border-t border-line px-3 py-3">
        <NavItem to="/settings" label="Settings" icon={Settings} onNavigate={onNavigate} />
        <p className="mt-2 flex items-center gap-2 px-2.5 text-xs text-ink-3" aria-live="polite">
          <span aria-hidden className={`size-2 rounded-full ${s.dot}`} />
          {s.text}
        </p>
      </div>
    </div>
  )
}

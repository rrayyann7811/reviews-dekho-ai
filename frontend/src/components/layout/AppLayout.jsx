import { Menu, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import ErrorBoundary from './ErrorBoundary'
import Logo from './Logo'
import Sidebar from './Sidebar'

export default function AppLayout() {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const { pathname } = useLocation()

  // Start each page at the top, like a normal website. (Braces matter: newer
  // browsers return a Promise from scrollTo, and an effect may only return a cleanup function.)
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [pathname])

  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e) => e.key === 'Escape' && setDrawerOpen(false)
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>

      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 hidden w-[232px] border-r border-line bg-surface lg:block">
        <Sidebar />
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-surface px-4 lg:hidden">
        <Logo />
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          className="flex size-9 items-center justify-center rounded-md text-ink-2 hover:bg-black/[0.04]"
          aria-label="Open navigation"
          aria-expanded={drawerOpen}
        >
          <Menu className="size-5" />
        </button>
      </header>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-ink/30" onClick={() => setDrawerOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[260px] bg-surface shadow-xl">
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              className="absolute right-3 top-3.5 flex size-8 items-center justify-center rounded-md text-ink-3 hover:bg-black/[0.04]"
              aria-label="Close navigation"
            >
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setDrawerOpen(false)} />
          </aside>
        </div>
      )}

      <main id="main" className="lg:pl-[232px]">
        <div className="mx-auto max-w-[1160px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8">
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </div>
      </main>
    </div>
  )
}

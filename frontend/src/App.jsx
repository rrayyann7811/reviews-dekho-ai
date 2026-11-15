import { lazy, Suspense } from 'react'
import { BrowserRouter, HashRouter, Route, Routes } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import Spinner from './components/ui/Spinner'
import { ServerStatusProvider } from './lib/serverStatus'
import { SettingsProvider } from './lib/settings'
import { STATIC_DEMO } from './lib/staticDemo'
import AnalyzeProduct from './pages/AnalyzeProduct'
import History from './pages/History'
import NotFound from './pages/NotFound'
import Overview from './pages/Overview'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import UploadReviews from './pages/UploadReviews'
import SupabaseEntry from './components/SupabaseEntry'

// The analysis and comparison pages are the largest, so they load on demand.
const ProductAnalysis = lazy(() => import('./pages/ProductAnalysis'))
const Compare = lazy(() => import('./pages/Compare'))

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Overview />} />
        <Route path="analyze" element={<AnalyzeProduct />} />
        <Route path="upload" element={<UploadReviews />} />
        <Route path="history" element={<History />} />
        <Route path="products/:productId" element={<Suspense fallback={<Spinner />}><ProductAnalysis /></Suspense>} />
        <Route path="compare" element={<Suspense fallback={<Spinner />}><Compare /></Suspense>} />
        <Route path="reports" element={<Reports />} />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

// The static demo uses #/ addresses, so it works from any folder (e.g. GitHub Pages) without server rewrites.
const Router = STATIC_DEMO ? HashRouter : BrowserRouter

export default function App() {
  // An unknown configured auth mode fails closed to the unconfigured sign-in screen.
  if (!STATIC_DEMO && (import.meta.env.VITE_AUTH_MODE || 'local') !== 'local') return <SupabaseEntry />
  return (
    <SettingsProvider>
      <ServerStatusProvider>
        <Router>
          <AppRoutes />
        </Router>
      </ServerStatusProvider>
    </SettingsProvider>
  )
}

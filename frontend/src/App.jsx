import { lazy, Suspense } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import AppLayout from './components/layout/AppLayout'
import Spinner from './components/ui/Spinner'
import { ServerStatusProvider } from './lib/serverStatus'
import { SettingsProvider } from './lib/settings'
import AnalyzeProduct from './pages/AnalyzeProduct'
import History from './pages/History'
import NotFound from './pages/NotFound'
import Overview from './pages/Overview'
import Reports from './pages/Reports'
import Settings from './pages/Settings'
import UploadReviews from './pages/UploadReviews'

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

export default function App() {
  return (
    <SettingsProvider>
      <ServerStatusProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </ServerStatusProvider>
    </SettingsProvider>
  )
}

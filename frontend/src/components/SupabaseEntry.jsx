import { useEffect, useState } from 'react'
import { loadSupabaseAdapter, supabaseConfig } from '../lib/supabaseAuth'
import HostedApp from './HostedApp'
import Spinner from './ui/Spinner'

function ConfiguredApp({ config }) {
  const [state, setState] = useState({ provider: null, failed: false })
  const [callbackLocation] = useState(() => ({ href: window.location.href }))
  useEffect(() => {
    let active = true, provider
    const url = new URL(callbackLocation.href)
    if (url.pathname.startsWith('/auth/') || url.searchParams.has('code') || /(?:access_token|refresh_token|error)=/.test(url.hash)) {
      window.history.replaceState(null, '', url.pathname)
    }
    void loadSupabaseAdapter(config, { location: callbackLocation, isActive: () => active }).then((value) => {
      provider = value
      if (active) setState({ provider, failed: false })
      else provider.dispose()
    }).catch(() => { if (active) setState({ provider: null, failed: true }) })
    return () => { active = false; provider?.dispose() }
  }, [config, callbackLocation])
  if (state.failed) return <HostedApp />
  if (!state.provider) return <main className="mx-auto max-w-sm px-4 py-10"><Spinner label="Preparing account sign-in…" /></main>
  return <HostedApp provider={state.provider} />
}

// Configuration is public, but still validated before loading/creating a client. No configured project by default.
export default function SupabaseEntry() {
  const [config] = useState(() => {
    if (import.meta.env.VITE_AUTH_MODE !== 'hosted') return null
    try { return supabaseConfig(import.meta.env, window.location.origin) } catch { return null }
  })
  useEffect(() => {
    if (!config && (window.location.pathname.startsWith('/auth/') || window.location.search || window.location.hash)) {
      window.history.replaceState(null, '', '/')
    }
  }, [config])
  return config ? <ConfiguredApp config={config} /> : <HostedApp />
}

import { useEffect, useLayoutEffect, useMemo, useSyncExternalStore } from 'react'
import { BrowserRouter, Navigate, useLocation, useNavigationType } from 'react-router-dom'
import { AppRoutes } from '../App'
import { invalidateAuthenticatedRequests, setAccessTokenProvider } from '../lib/api'
import { createSessionController } from '../lib/session'
import { ServerStatusProvider } from '../lib/serverStatus'
import { clearPendingImport, HostedUploadAccount, readPendingImport } from '../lib/pendingImport'
import { SettingsProvider } from '../lib/settings'
import Logo from './layout/Logo'
import Button from './ui/Button'
import { Field, Input } from './ui/Field'
import Panel from './ui/Panel'
import Spinner from './ui/Spinner'
import AccountActions from './AccountActions'

function SignIn({ state, controller, configured, provider }) {
  const busy = state.status === 'signingIn' || state.status === 'signingOut'
  const disabled = busy || !configured
  function submit(event) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)
    const operation = controller.signIn({ email: data.get('email'), password: data.get('password') })
    form.reset() // raw passwords do not remain in application state or the form while awaiting the provider
    void operation
  }
  return (
    <main className="mx-auto max-w-sm space-y-6 px-4 py-10">
      <Logo />
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h1>
        <p id="auth-help" className="mt-2 text-sm text-ink-2">
          {configured ? 'Sign in through the configured identity provider to access your private review workspace.'
            : 'Account sign-in is being prepared. No production identity provider is connected in this build.'}
        </p>
      </div>
      <Panel title="Your account">
        <form onSubmit={submit} aria-describedby="auth-help" className="space-y-4" aria-busy={busy}>
          <Field label="Email">{(props) => <Input {...props} type="email" name="email" autoComplete="username" required disabled={disabled} />}</Field>
          <Field label="Password">{(props) => <Input {...props} type="password" name="password" autoComplete="current-password" required disabled={disabled} />}</Field>
          {state.error && <p role="alert" className="text-sm text-neg">{state.error}</p>}
          {!configured && <p role="status" className="text-sm text-ink-3">Sign-in is not configured. No account credentials will be submitted.</p>}
          <Button type="submit" disabled={disabled}>{state.status === 'signingOut' ? 'Signing out…' : busy ? 'Signing in…' : 'Sign in'}</Button>
        </form>
      </Panel>
      {!busy && configured && <AccountActions provider={provider} />}
    </main>
  )
}

// Browser history can contain a previous account's product IDs or comparison query parameters.
function ScopedRoutes({ scope }) {
  const location = useLocation()
  const action = useNavigationType()
  const historyScope = window.history.state?.rdAccountScope
  const stale = action === 'POP' && historyScope !== scope && (location.pathname !== '/' || location.search || location.hash)
  useLayoutEffect(() => {
    if (!stale) window.history.replaceState({ ...window.history.state, rdAccountScope: scope }, '')
  }, [scope, location, stale])
  if (stale) return <Navigate to="/" replace />
  return <AppRoutes />
}

// A future managed-provider adapter is passed here explicitly. There is no production/fake provider fallback.
export default function HostedApp({ provider = null }) {
  const controller = useMemo(() => createSessionController(provider, { onBoundary: (previous, next, cleared) => {
    invalidateAuthenticatedRequests()
    if (cleared || (previous && previous !== next)) clearPendingImport()
    else if (next) readPendingImport(next)
    window.history.replaceState(null, '', '/')
  } }), [provider])
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot)
  const scope = `${controller.id}:${state.epoch}`
  useEffect(() => {
    if (state.status === 'signedOut') clearPendingImport()
  }, [state.status])
  useEffect(() => {
    setAccessTokenProvider(controller.getAccessToken, { onUnauthorized: controller.rejectAccessToken })
    void controller.start()
    return () => { controller.stop(); setAccessTokenProvider(null) }
  }, [controller])

  if (state.status === 'restoring') return (
    <main className="mx-auto max-w-sm space-y-6 px-4 py-10"><Logo /><h1 className="text-2xl font-semibold">Checking your session</h1><Spinner label="Restoring or refreshing your session…" /></main>
  )
  if (state.status === 'recovery') return <main className="mx-auto max-w-sm space-y-6 px-4 py-10">
    <Logo /><h1 className="text-2xl font-semibold">Reset your password</h1>
    <AccountActions key={scope} provider={provider} recovery onCancel={() => { void controller.signOut() }} />
  </main>
  if (state.status !== 'signedIn') return <SignIn key={scope} state={state} controller={controller} configured={state.status !== 'unconfigured'} provider={provider} />
  return (
    <SettingsProvider key={scope}>
      <ServerStatusProvider>
        <div className="lg:pl-[232px]"><section aria-label="Account" className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3 text-sm">
          <span>Signed in{state.user.email ? ` as ${state.user.email}` : ''}</span>
          <Button variant="secondary" size="sm" onClick={() => { void controller.signOut() }}>Sign out</Button>
        </section></div>
        <HostedUploadAccount.Provider value={state.accountScope}>
          <BrowserRouter><ScopedRoutes scope={scope} /></BrowserRouter>
        </HostedUploadAccount.Provider>
      </ServerStatusProvider>
    </SettingsProvider>
  )
}

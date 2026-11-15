// Supabase is an identity provider only. Application data still goes through the JWT-protected API.
export function supabaseConfig(env, origin) {
  const url = new URL(env.VITE_SUPABASE_URL)
  const site = new URL(origin)
  if (url.protocol !== 'https:' || !/^[a-z0-9-]+\.supabase\.co$/.test(url.hostname)
    || url.port || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('Invalid Supabase project URL')
  }
  // Accept modern publishable keys only. Reject legacy JWT and privileged sb_secret keys outright.
  const key = env.VITE_SUPABASE_PUBLISHABLE_KEY
  if (!/^sb_publishable_[A-Za-z0-9_-]{16,256}$/.test(key || '')) throw new Error('A publishable client key is required')
  if (site.origin !== origin || (site.protocol !== 'https:' && !(site.protocol === 'http:'
    && ['localhost', '127.0.0.1', '[::1]'].includes(site.hostname)))) throw new Error('An HTTPS application origin is required')
  return { url: url.origin, key, issuer: `${url.origin}/auth/v1`, origin: site.origin,
    storageKey: `rd-supabase-${url.hostname}-auth` }
}

export function createSupabaseAdapter(client, config, { location = window.location,
  history = window.history, storage = window.localStorage, createRecoveryAuth } = {}) {
  const auth = client.auth
  const recoveryKey = `${config.storageKey}-recovery`
  let recoveryOwner = storage.getItem(recoveryKey)
  let currentOwner = null
  let generation = 0
  let actionRevision = 0
  let blocked = false
  let operation = false
  let operationFlight = null
  let last = undefined
  let initial = null
  let initialError = false
  let callbackFlight = null
  let refreshFlight = null
  const listeners = new Set()
  const markRecovery = (owner) => {
    recoveryOwner = owner || null
    if (owner) storage.setItem(recoveryKey, owner)
    else storage.removeItem(recoveryKey)
  }
  const normalized = (session) => {
    if (!session) return null
    if (typeof session.access_token !== 'string' || !session.access_token || !session.user?.id
      || session.user.is_anonymous === true || !Number.isFinite(session.expires_at)) throw new Error('Invalid provider session')
    return { issuer: config.issuer, user: { id: session.user.id, email: session.user.email || '' },
      accessToken: session.access_token, expiresAt: session.expires_at * 1000, recoveryRequired: recoveryOwner === session.user.id }
  }
  const emit = (value) => {
    const fingerprint = JSON.stringify(value)
    if (fingerprint === last) return
    last = fingerprint
    currentOwner = value?.user.id ?? null
    for (const listener of listeners) listener(value)
  }
  // Synchronous callback: never await SDK methods while handling an SDK auth notification.
  const { data: { subscription } } = auth.onAuthStateChange((event, session) => {
    // Token rotation cannot switch accounts. Ignore an obsolete refresh event for a previous owner.
    if (event === 'TOKEN_REFRESHED' && currentOwner && session?.user.id !== currentOwner) return
    generation++
    if (blocked || initial) return
    if (operation) {
      // External logout/account switches must clear the old recovery UI even during an SDK mutation.
      if (event === 'SIGNED_OUT') { markRecovery(false); emit(null) }
      else if (event === 'SIGNED_IN' && currentOwner && session?.user.id !== currentOwner) {
        try { emit(normalized(session)) } catch { blocked = true; emit(null) }
      }
      return
    }
    if (event === 'SIGNED_OUT') { markRecovery(false); emit(null); return }
    if (event === 'PASSWORD_RECOVERY') markRecovery(session?.user.id)
    if (['INITIAL_SESSION', 'SIGNED_IN', 'TOKEN_REFRESHED', 'USER_UPDATED', 'PASSWORD_RECOVERY'].includes(event)) {
      try { emit(normalized(session)) } catch { blocked = true; emit(null) }
    }
  })
  const result = (value) => {
    if (value.error) throw new Error('Identity provider operation failed')
    return value.data
  }
  const callback = new URL(location.href)
  if (['/auth/confirm', '/auth/recovery'].includes(callback.pathname)) {
    // Capture once, then remove codes/errors/tokens before any dashboard/router boundary can run.
    history.replaceState(null, '', callback.pathname)
    const codes = callback.searchParams.getAll('code')
    const flows = callback.searchParams.getAll('sb_flow_id')
    if (codes.length !== 1 || !codes[0] || callback.hash || callback.searchParams.has('error')
      || flows.length > 1 || (flows.length && !/^[A-Za-z0-9_-]{8,64}$/.test(flows[0]))) initialError = true
    else initial = { code: codes[0], flowId: flows[0], recovery: callback.pathname === '/auth/recovery' }
  } else if (callback.searchParams.has('code') || /(?:access_token|refresh_token|error)=/.test(callback.hash)) {
    history.replaceState(null, '', '/')
    initialError = true // implicit-token and unexpected-path callbacks are never accepted
  }
  const restore = async () => {
    if (initialError) throw new Error('The account callback is invalid or expired')
    if (blocked) return null
    if (initial) {
      if (!callbackFlight) callbackFlight = (async () => {
        operation = true
        try {
          const data = result(await (initial.flowId ? auth.exchangeCodeForSession(initial.code, { flowId: initial.flowId })
            : auth.exchangeCodeForSession(initial.code)))
          if (!data.session) throw new Error('No callback session')
          markRecovery(initial.recovery || data.redirectType === 'recovery' ? data.session?.user.id : null)
          currentOwner = data.session?.user.id ?? null
          if (!recoveryOwner) {
            // Email/signup AMR is not password authentication. Require a fresh password login after
            // confirmation instead of mounting private views with a confirmation-only token.
            blocked = true
            result(await auth.signOut({ scope: 'local' }))
            return null
          }
          return normalized(data.session)
        } catch { blocked = true; throw new Error('The account callback is invalid or expired') }
        finally { initial = null; operation = false }
      })()
      return callbackFlight
    }
    const ticket = generation
    const data = result(await auth.getSession())
    if (ticket !== generation) throw new DOMException('The provider session changed', 'AbortError')
    currentOwner = data.session?.user.id ?? null
    return normalized(data.session)
  }
  const exclusive = async (fn) => {
    if (operation) throw new Error('Another account operation is in progress')
    operation = true
    operationFlight = fn()
    try { return await operationFlight } finally { operation = false; operationFlight = null }
  }
  return {
    getSession: restore,
    signIn: (credentials) => exclusive(async () => {
      const ticket = ++actionRevision
      initialError = false
      blocked = true
      const data = result(await auth.signInWithPassword({ email: credentials.email, password: credentials.password }))
      if (ticket !== actionRevision) throw new DOMException('The account changed', 'AbortError')
      markRecovery(false)
      const session = normalized(data.session)
      if (!session || session.expiresAt <= Date.now()) throw new Error('No valid sign-in session')
      blocked = false
      currentOwner = session.user.id
      return session
    }),
    signOut: async () => {
      actionRevision++
      generation++
      blocked = true
      markRecovery(false)
      emit(null)
      // Let already-started SDK writes finish before removing the stored session. Never allow a delayed
      // sign-in/refresh to persist an old account after this sign-out has completed.
      await Promise.allSettled([operationFlight, callbackFlight, refreshFlight].filter(Boolean))
      result(await auth.signOut({ scope: 'local' }))
    },
    refreshSession: () => {
      if (refreshFlight) return refreshFlight
      const ticket = generation
      refreshFlight = (async () => {
        try {
          if (blocked) throw new Error('Signed out')
          const data = result(await auth.refreshSession())
          if (blocked) throw new Error('Signed out')
          // SDK refresh emits TOKEN_REFRESHED before resolving. Use its canonical session if superseded.
          if (ticket !== generation) return restore()
          const session = normalized(data.session)
          if (!session || session.expiresAt <= Date.now()) throw new Error('Expired session')
          return session
        } catch (error) {
          if (ticket === generation) blocked = true
          throw error
        }
        finally { refreshFlight = null }
      })()
      return refreshFlight
    },
    register: (credentials) => exclusive(async () => {
      const data = result(await auth.signUp({ email: credentials.email, password: credentials.password,
        options: { emailRedirectTo: `${config.origin}/auth/confirm` } }))
      if (data.session) {
        blocked = true
        result(await auth.signOut({ scope: 'local' }))
        emit(null)
        throw new Error('Email confirmation must be enabled')
      }
      return 'If registration is available, check your email to confirm your account.'
    }),
    requestPasswordReset: async (email) => {
      result(await auth.resetPasswordForEmail(email, { redirectTo: `${config.origin}/auth/recovery` }))
      return 'If an account matches that email, you will receive a password reset link.'
    },
    updatePassword: (password) => exclusive(async () => {
      if (!recoveryOwner || blocked || !createRecoveryAuth) throw new Error('Open a valid password reset link first')
      const ticket = generation
      const data = result(await auth.getUser())
      const stored = result(await auth.getSession()).session
      if (ticket !== generation || data.user?.id !== recoveryOwner || stored?.user.id !== recoveryOwner) throw new Error('The recovery account changed')
      // Bind this sensitive mutation to an isolated, non-persistent SDK session. updateUser on the
      // shared client re-reads storage asynchronously and could otherwise target a switched account.
      const isolated = createRecoveryAuth()
      try {
        result(await isolated.setSession({ access_token: stored.access_token, refresh_token: stored.refresh_token }))
        const verified = result(await isolated.getUser())
        if (ticket !== generation || blocked || verified.user?.id !== recoveryOwner) throw new Error('The recovery account changed')
        result(await isolated.updateUser({ password }))
        if (ticket !== generation || blocked) throw new Error('The recovery account changed')
        markRecovery(false)
        blocked = true
        emit(null)
        result(await auth.signOut({ scope: 'local' }))
      } finally { isolated.dispose?.() }
    }),
    onSessionChange: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    dispose: () => { actionRevision++; generation++; blocked = true; listeners.clear(); subscription.unsubscribe(); auth.dispose?.() },
  }
}

export async function loadSupabaseAdapter(config, options) {
  // Inline the Vite mode check so dependency scanning removes the SDK import before emitting demo chunks.
  const sdk = import.meta.env.MODE === 'staticdemo' ? null : await import('@supabase/supabase-js')
  if (!sdk) throw new Error('Authentication is unavailable in the static demo')
  const { createClient } = sdk
  if (options?.isActive && !options.isActive()) throw new DOMException('The account view was closed', 'AbortError')
  const client = createClient(config.url, config.key, { auth: { flowType: 'pkce', persistSession: true,
    autoRefreshToken: false, detectSessionInUrl: false, storageKey: config.storageKey } })
  const createRecoveryAuth = () => createClient(config.url, config.key, { auth: { flowType: 'pkce',
    persistSession: false, autoRefreshToken: false, detectSessionInUrl: false,
    storageKey: `${config.storageKey}-operation-${crypto.randomUUID()}` } }).auth
  try { return createSupabaseAdapter(client, config, { ...options, createRecoveryAuth }) } catch (error) { client.auth.dispose?.(); throw error }
}

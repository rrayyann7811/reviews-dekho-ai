// Provider-independent session state. Only a configured identity provider creates/refreshes accounts/tokens.
// Session metadata is for UI isolation only; backend authorization still verifies the signed access token.
const EXPIRED = 'Your session expired or could not be refreshed. Sign in again.'
const CHANGED = () => new DOMException('The account session changed.', 'AbortError')
const identity = (session) => session ? `${session.issuer}\0${session.user.id}` : null

function normalize(value) {
  if (value === null) return null
  if (!value || typeof value.issuer !== 'string' || !value.issuer || typeof value.user?.id !== 'string'
    || !value.user.id || typeof value.accessToken !== 'string' || !value.accessToken
    || !Number.isFinite(value.expiresAt)) throw new Error('Invalid identity-provider session')
  return { issuer: value.issuer, user: { id: value.user.id,
    email: typeof value.user.email === 'string' ? value.user.email.slice(0, 254) : '' },
  accessToken: value.accessToken, expiresAt: value.expiresAt, recoveryRequired: value.recoveryRequired === true }
}

export function createSessionController(provider, { onBoundary = () => {}, now = Date.now, timeoutMs = 10000 } = {}) {
  const configured = ['getSession', 'signIn', 'signOut', 'refreshSession', 'onSessionChange']
    .every((name) => typeof provider?.[name] === 'function')
  let snapshot = { status: configured ? 'restoring' : 'unconfigured', user: null, epoch: 0, error: '' }
  let current = null
  let revision = 0
  let active = false
  let acceptEvents = true
  let unsubscribe = null
  let expiryTimer = null
  let refreshFlight = null
  const listeners = new Set()
  const publish = (patch) => {
    snapshot = { ...snapshot, ...patch }
    for (const listener of listeners) listener()
  }
  const valid = () => current && current.expiresAt > now()
  const providerCall = async (fn) => {
    let timer
    try {
      return await Promise.race([Promise.resolve().then(fn), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('Identity provider timed out')), timeoutMs)
      })])
    } finally { clearTimeout(timer) }
  }
  const clear = (error = '', blockEvents = false) => {
    revision++
    acceptEvents = !blockEvents
    current = null
    refreshFlight = null
    clearTimeout(expiryTimer)
    onBoundary()
    publish({ status: 'signedOut', user: null, epoch: snapshot.epoch + 1, error })
  }
  const scheduleExpiry = () => {
    clearTimeout(expiryTimer)
    if (!current) return
    const ticket = revision
    expiryTimer = setTimeout(() => {
      if (!active || ticket !== revision) return
      if (valid()) scheduleExpiry() // very long lifetimes may exceed the browser timer range
      else void refresh().catch(() => {})
    }, Math.min(Math.max(0, current.expiresAt - now()), 2147483647))
  }
  const apply = (session) => {
    revision++
    const changed = identity(current) !== identity(session) || Boolean(current?.recoveryRequired) !== Boolean(session?.recoveryRequired)
    if (changed) refreshFlight = null
    current = session
    if (changed) onBoundary()
    publish({ status: session ? (valid() ? (session.recoveryRequired ? 'recovery' : 'signedIn') : 'restoring') : 'signedOut', user: session?.user ?? null,
      epoch: snapshot.epoch + (changed ? 1 : 0), error: '' })
    scheduleExpiry()
  }
  const refresh = () => {
    if (refreshFlight) return refreshFlight
    if (!active || !current) return Promise.reject(CHANGED())
    const ticket = revision
    const epoch = snapshot.epoch
    const owner = identity(current)
    // Expired credentials never leave private dashboard content visible while refresh is pending.
    if (!valid()) publish({ status: 'restoring' })
    let flight
    flight = providerCall(() => provider.refreshSession()).then((value) => {
      if (!active || ticket !== revision) {
        if (active && snapshot.epoch === epoch && valid()) return current.accessToken
        throw CHANGED()
      }
      const session = normalize(value)
      if (!session || session.expiresAt <= now()) throw new Error(EXPIRED)
      apply(session)
      if (identity(session) !== owner || session.recoveryRequired) throw CHANGED()
      return current.accessToken
    }).catch((err) => {
      if (active && ticket === revision) clear(EXPIRED, true)
      throw err
    }).finally(() => { if (refreshFlight === flight) refreshFlight = null })
    refreshFlight = flight
    return flight
  }
  const sessionEvent = (value) => {
    if (!active || !acceptEvents) return
    try {
      const session = normalize(value)
      if (!session) clear()
      else {
        apply(session)
        if (!valid()) void refresh().catch(() => {})
      }
    } catch { clear(EXPIRED, true) }
  }

  return {
    id: crypto.randomUUID(), // non-secret UI/history scope; never sent as an authorization identity
    getSnapshot: () => snapshot,
    subscribe: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    start: async () => {
      if (!configured || active) return
      active = true
      acceptEvents = true
      const ticket = ++revision
      publish({ status: 'restoring', error: '' })
      try {
        unsubscribe = provider.onSessionChange(sessionEvent)
        const value = await providerCall(() => provider.getSession())
        if (!active || ticket !== revision) return
        const session = normalize(value)
        if (!session) clear()
        else {
          apply(session)
          if (!valid()) await refresh()
        }
      } catch {
        if (active && ticket === revision) clear('Couldn’t restore your session. Sign in again.')
      }
    },
    stop: () => {
      active = false
      revision++
      acceptEvents = false
      current = null
      refreshFlight = null
      clearTimeout(expiryTimer)
      unsubscribe?.()
      unsubscribe = null
      onBoundary()
      publish({ status: configured ? 'restoring' : 'unconfigured', user: null, epoch: snapshot.epoch + 1 })
    },
    signIn: async (credentials) => {
      if (!configured || !active || snapshot.status === 'signingOut') return
      clear()
      acceptEvents = true
      const ticket = revision
      publish({ status: 'signingIn' })
      try {
        // Passwords are passed straight through; never retained in controller state or browser storage.
        const value = await providerCall(() => provider.signIn(credentials))
        if (!active || ticket !== revision) return
        const session = normalize(value)
        if (!session || session.expiresAt <= now()) throw new Error('Invalid sign-in session')
        apply(session)
      } catch {
        if (active && ticket === revision) clear('Sign-in failed. Check your email and password, then try again.')
      }
    },
    signOut: async () => {
      if (!configured || !active) return
      clear('', true) // local isolation is immediate, even if remote sign-out is slow or fails
      const ticket = revision
      publish({ status: 'signingOut' })
      try { await providerCall(() => provider.signOut()) } catch {
        if (active && ticket === revision) publish({ error: 'Signed out on this device. The identity provider could not confirm remote sign-out.' })
      } finally { if (active && ticket === revision) publish({ status: 'signedOut' }) }
    },
    getAccessToken: async () => {
      if (!active || !current || current.recoveryRequired) throw new Error('Sign in to access your review data.')
      if (!valid()) return refresh()
      return current.accessToken
    },
    rejectAccessToken: (token) => {
      // A late 401 from an old access token must not log out a successfully refreshed session.
      if (active && current?.accessToken === token) clear(EXPIRED, true)
    },
  }
}

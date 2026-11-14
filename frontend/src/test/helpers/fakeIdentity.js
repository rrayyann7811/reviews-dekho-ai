// OFFLINE TEST FIXTURE ONLY. These opaque strings are not JWTs and cannot authenticate to the real backend.
export function fakeSession(user = 'alice', { expiresAt = Date.now() + 60000, token = `OFFLINE-TEST-${user}-1`, issuer = 'https://test-identity.invalid' } = {}) {
  return { issuer, user: { id: user, email: `${user}@example.invalid` }, accessToken: token, expiresAt }
}

export function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

export function fakeProvider(initial = null) {
  let session = initial
  const listeners = new Set()
  return {
    getSession: async () => session,
    signIn: async ({ email, password }) => {
      if (password !== 'offline-test-password') throw new Error('test provider rejected credentials')
      session = fakeSession(email.split('@')[0])
      return session
    },
    signOut: async () => { session = null },
    refreshSession: async () => {
      if (!session) return null
      session = fakeSession(session.user.id, { token: `OFFLINE-TEST-${session.user.id}-refreshed` })
      return session
    },
    onSessionChange: (listener) => { listeners.add(listener); return () => listeners.delete(listener) },
    change: (next) => { session = next; for (const listener of listeners) listener(next) },
    listenerCount: () => listeners.size,
  }
}

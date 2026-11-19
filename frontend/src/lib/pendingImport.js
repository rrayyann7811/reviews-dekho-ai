import { createContext } from 'react'

export const HostedUploadAccount = createContext(null)
const SLOT = 'reviews-dekho.pending-import'
const WINDOW_MS = 7 * 24 * 60 * 60 * 1000

export function clearPendingImport() {
  try { sessionStorage.removeItem(SLOT) } catch { /* Storage can be disabled. */ }
}

export function readPendingImport(owner) {
  if (!owner) return null
  try {
    const pending = JSON.parse(sessionStorage.getItem(SLOT))
    if (pending?.owner === owner && /^[\w-]{16,64}$/.test(pending.key) &&
        Number.isFinite(pending.startedAt) && Date.now() - pending.startedAt < WINDOW_MS) return pending
    clearPendingImport()
  } catch { clearPendingImport() }
  return null
}

export function savePendingImport(owner) {
  const pending = { owner, key: crypto.randomUUID(), startedAt: Date.now() }
  try { sessionStorage.setItem(SLOT, JSON.stringify(pending)) } catch { /* The current page still has the key. */ }
  return pending
}

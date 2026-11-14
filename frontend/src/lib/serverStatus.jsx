import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'
import { STATIC_DEMO } from './staticDemo'

// Tracks whether the FastAPI backend is reachable: 'checking' | 'online' | 'offline'.
const ServerStatusContext = createContext({ status: 'checking', check: () => {} })

export function ServerStatusProvider({ children }) {
  // The static demo has no backend: it is "offline" from the start and never pings.
  const [status, setStatus] = useState(STATIC_DEMO ? 'offline' : 'checking')
  const ping = useCallback(() => {
    if (STATIC_DEMO) return
    api.health().then(() => setStatus('online'), () => setStatus('offline'))
  }, [])
  const check = useCallback(() => {
    if (STATIC_DEMO) return
    setStatus('checking')
    ping()
  }, [ping])
  useEffect(() => {
    ping()
  }, [ping])
  return <ServerStatusContext.Provider value={{ status, check }}>{children}</ServerStatusContext.Provider>
}

// oxlint-disable-next-line react/only-export-components
export const useServerStatus = () => useContext(ServerStatusContext)

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from './api'

// Tracks whether the FastAPI backend is reachable: 'checking' | 'online' | 'offline'.
const ServerStatusContext = createContext({ status: 'checking', check: () => {} })

export function ServerStatusProvider({ children }) {
  const [status, setStatus] = useState('checking')
  const ping = useCallback(() =>
    api.health().then(() => setStatus('online'), () => setStatus('offline')), [])
  const check = useCallback(() => {
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

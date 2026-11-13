import { createContext, useCallback, useContext, useState } from 'react'

const KEY = 'rd-settings'
const DEFAULTS = { showDemo: true, introDismissed: false }

function load() {
  try {
    return { ...DEFAULTS, ...JSON.parse(localStorage.getItem(KEY) || '{}') }
  } catch {
    return DEFAULTS
  }
}

const SettingsContext = createContext(null)

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(load)
  const update = useCallback((patch) => {
    setSettings((current) => {
      const next = { ...current, ...patch }
      try {
        localStorage.setItem(KEY, JSON.stringify(next))
      } catch {
        // Storage can be unavailable (private mode); settings then last for this session only.
      }
      return next
    })
  }, [])
  return <SettingsContext.Provider value={{ settings, update }}>{children}</SettingsContext.Provider>
}

// oxlint-disable-next-line react/only-export-components
export const useSettings = () => useContext(SettingsContext)

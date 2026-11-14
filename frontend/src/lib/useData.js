import { useEffect, useState } from 'react'
import { DEMO_ID, demoAnalysis, demoProductSummary } from '../demo/demo'
import { api } from './api'
import { useServerStatus } from './serverStatus'
import { useSettings } from './settings'

/** Analysed products: the demo product (if enabled) plus everything stored by the backend. */
export function useProducts() {
  const { status } = useServerStatus()
  const { settings } = useSettings()
  // `forStatus` records which server state the result belongs to, so stale results are ignored.
  const [remote, setRemote] = useState({ forStatus: null, items: [], error: null })

  useEffect(() => {
    if (status !== 'online') return
    let active = true
    api
      .listProducts()
      .then((items) => active && setRemote({ forStatus: status, items, error: null }))
      .catch((error) => active && setRemote({ forStatus: status, items: [], error }))
    return () => {
      active = false
    }
  }, [status])

  const fresh = status === 'online' && remote.forStatus === 'online'
  return {
    items: [...(settings.showDemo ? [demoProductSummary] : []), ...(fresh ? remote.items : [])],
    loading: status === 'checking' || (status === 'online' && !fresh),
    error: fresh ? remote.error : null,
    serverOffline: status === 'offline',
  }
}

/** Full analysis for one product. The demo product is served locally. */
export function useAnalysis(productId) {
  const isDemo = productId === DEMO_ID
  const [result, setResult] = useState({ id: null, data: null, error: null })
  const [version, setVersion] = useState(0) // bump to load the analysis again

  useEffect(() => {
    if (isDemo) return
    let active = true
    api
      .getAnalysis(productId)
      .then((data) => active && setResult({ id: productId, data, error: null }))
      .catch((error) => active && setResult({ id: productId, data: null, error }))
    return () => {
      active = false
    }
  }, [productId, isDemo, version])

  const reload = () => setVersion((v) => v + 1)
  if (isDemo) return { data: demoAnalysis, loading: false, error: null, reload }
  const current = result.id === productId
  return { data: current ? result.data : null, loading: !current, error: current ? result.error : null, reload }
}

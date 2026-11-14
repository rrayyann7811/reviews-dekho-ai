import { useEffect, useState } from 'react'
import { api } from './api'

/** The analysis runs of a product (newest first). Shared by the Reports and Compare pages. */
export function useRuns(productId, enabled) {
  const [runs, setRuns] = useState({ for: null, items: [], error: '' })
  useEffect(() => {
    if (!enabled) return
    let active = true
    api.listHistory(productId)
      .then((items) => active && setRuns({ for: productId, items, error: '' }))
      .catch((err) => active && setRuns({ for: productId, items: [], error: err.message }))
    return () => { active = false }
  }, [productId, enabled])
  const current = runs.for === productId
  return { items: current ? runs.items : [], error: current ? runs.error : '', loaded: current }
}

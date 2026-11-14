import { Download } from 'lucide-react'
import { useState } from 'react'
import { api } from '../lib/api'
import Button from './ui/Button'

const NAMES = { pdf: 'PDF', csv: 'CSV' }

/** Downloads a report for one analysis run, showing progress, the file name or the server's error. */
export default function ReportDownload({ productId, analysisId, format = 'pdf', variant = 'secondary', className = '' }) {
  const [state, setState] = useState({ busy: false, error: '', done: '' })

  async function download() {
    setState({ busy: true, error: '', done: '' })
    try {
      const name = await api.downloadReport(productId, format, analysisId)
      setState({ busy: false, error: '', done: name })
    } catch (err) {
      setState({ busy: false, error: err.message, done: '' })
    }
  }

  return (
    <div className={`flex flex-col items-start gap-1.5 ${className}`}>
      <Button variant={variant} onClick={download} disabled={state.busy}>
        <Download aria-hidden className="size-4" />
        {state.busy ? `Preparing ${NAMES[format]}…` : `Download ${NAMES[format]}`}
      </Button>
      {state.error && <p role="alert" className="max-w-xs text-xs text-neg">{state.error}</p>}
      {state.done && <p role="status" className="text-xs text-ink-3">Downloaded {state.done}</p>}
    </div>
  )
}

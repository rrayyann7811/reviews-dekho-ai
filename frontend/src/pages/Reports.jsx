import { FileText, Table2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ReportDownload from '../components/ReportDownload'
import ServerNotice from '../components/ServerNotice'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import { DEMO_ID } from '../demo/demo'
import { api } from '../lib/api'
import { formatDate } from '../lib/format'
import { useServerStatus } from '../lib/serverStatus'
import { useProducts } from '../lib/useData'

const FORMATS = [
  { id: 'pdf', icon: FileText, title: 'PDF report',
    text: 'Key figures, charts, feature analysis, an evidence-backed summary with exact review excerpts, the method and its limitations.' },
  { id: 'csv', icon: Table2, title: 'CSV export',
    text: 'Every review of the run with its sentiment label, score and detected features, for use in Excel.' },
]

function unavailableReason(status, productId, runs) {
  if (status !== 'online') return 'Available when the server is running.'
  if (!productId) return 'Choose a product first.'
  if (productId === DEMO_ID) return 'The demo product is built into the app and can’t be exported. Upload a review file to export its analysis.'
  if (runs.error) return runs.error
  if (runs.loaded && runs.items.length === 0) return 'This product hasn’t been analysed yet.'
  return null
}

/** The analysis runs of a product (newest first), for choosing which one to report on. */
function useRuns(productId, enabled) {
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

export default function Reports() {
  const { items } = useProducts()
  const { status } = useServerStatus()
  const [productId, setProductId] = useState('')
  const [runId, setRunId] = useState('')
  const runs = useRuns(productId, status === 'online' && !!productId && productId !== DEMO_ID)
  const reason = unavailableReason(status, productId, runs)

  return (
    <>
      <PageHeader title="Reports" description="Download an analysis to share or keep." />
      <ServerNotice feature="Generating reports" />
      <Panel>
        <div className="grid gap-4 sm:grid-cols-2 lg:max-w-3xl">
          <Field label="Product">
            {(props) => (
              <Select {...props} value={productId} onChange={(e) => { setProductId(e.target.value); setRunId('') }}>
                <option value="">Choose a product…</option>
                {items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </Select>
            )}
          </Field>
          {runs.items.length > 0 && (
            <Field label="Analysis run" hint="Each run is a saved snapshot; the report uses only that run.">
              {(props) => (
                <Select {...props} value={runId} onChange={(e) => setRunId(e.target.value)}>
                  {runs.items.map((run, i) => (
                    <option key={run.id} value={i === 0 ? '' : run.id}>
                      {i === 0 ? 'Latest' : 'Run'} #{run.id} · {formatDate(run.createdAt)} · {run.totalReviews} reviews
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
        </div>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {FORMATS.map(({ id, icon: Icon, title, text }) => (
            <div key={id} className="flex flex-col rounded-lg border border-line p-4">
              <div className="flex items-center gap-2">
                <Icon aria-hidden className="size-4 text-ink-3" />
                <h2 className="text-sm font-semibold">{title}</h2>
              </div>
              <p className="mt-1 flex-1 text-[13px] text-ink-3">{text} Reviewer names are left out.</p>
              {reason ? (
                <p className="mt-4 text-[13px] text-ink-3">{reason}</p>
              ) : (
                <ReportDownload key={`${productId}-${runId}`} productId={productId} analysisId={runId || undefined}
                  format={id} className="mt-4" />
              )}
            </div>
          ))}
        </div>
      </Panel>
    </>
  )
}

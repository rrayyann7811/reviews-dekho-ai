import { FileText, Table2 } from 'lucide-react'
import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ReportDownload from '../components/ReportDownload'
import RunSelect from '../components/RunSelect'
import ServerNotice from '../components/ServerNotice'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import { DEMO_ID } from '../demo/demo'
import { useServerStatus } from '../lib/serverStatus'
import { useProducts } from '../lib/useData'
import { useRuns } from '../lib/useRuns'
import { STATIC_DEMO, STATIC_DEMO_TEXT } from '../lib/staticDemo'

const FORMATS = [
  { id: 'pdf', icon: FileText, title: 'PDF report',
    text: 'Key figures, charts, feature analysis, an evidence-backed summary with exact review excerpts, the method and its limitations.' },
  { id: 'csv', icon: Table2, title: 'CSV export',
    text: 'Every review of the run with its sentiment label, score and detected features, for use in Excel.' },
]

function unavailableReason(status, productId, runs) {
  if (STATIC_DEMO) return STATIC_DEMO_TEXT.unavailable
  if (status !== 'online') return 'Available when the server is running.'
  if (!productId) return 'Choose a product first.'
  if (productId === DEMO_ID) return 'The demo product is built into the app and can’t be exported. Upload a review file to export its analysis.'
  if (runs.error) return runs.error
  if (runs.loaded && runs.items.length === 0) return 'This product hasn’t been analysed yet.'
  return null
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
            <RunSelect runs={runs.items} value={runId} onChange={setRunId}
              hint="Each run is a saved snapshot; the report uses only that run." />
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

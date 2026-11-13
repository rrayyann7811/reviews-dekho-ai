import { FileText, Table2 } from 'lucide-react'
import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ServerNotice from '../components/ServerNotice'
import { buttonClasses } from '../components/ui/buttonStyles'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import { DEMO_ID } from '../demo/demo'
import { api } from '../lib/api'
import { useServerStatus } from '../lib/serverStatus'
import { useProducts } from '../lib/useData'

const FORMATS = [
  { id: 'pdf', icon: FileText, title: 'PDF report', text: 'A printable summary: key figures, charts, strengths, complaints and example reviews.', available: false },
  { id: 'csv', icon: Table2, title: 'CSV export', text: 'Every review with its sentiment label, score and detected features, for use in Excel.', available: true },
]

function unavailableReason({ available }, status, productId) {
  if (!available) return 'Not available yet. Use the CSV export for now.'
  if (status !== 'online') return 'Available when the server is running.'
  if (!productId) return 'Choose a product first.'
  if (productId === DEMO_ID) return 'The demo product is built into the app and can’t be exported. Upload a review file to export its analysis.'
  return null
}

export default function Reports() {
  const { items } = useProducts()
  const { status } = useServerStatus()
  const [productId, setProductId] = useState('')

  return (
    <>
      <PageHeader title="Reports" description="Download an analysis to share or keep." />
      <ServerNotice feature="Generating reports" />
      <Panel>
        <Field label="Product" className="max-w-md">
          {(props) => (
            <Select {...props} value={productId} onChange={(e) => setProductId(e.target.value)}>
              <option value="">Choose a product…</option>
              {items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </Select>
          )}
        </Field>
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {FORMATS.map((format) => {
            const { id, icon: Icon, title, text } = format
            const reason = unavailableReason(format, status, productId)
            return (
              <div key={id} className="flex flex-col rounded-lg border border-line p-4">
                <div className="flex items-center gap-2">
                  <Icon aria-hidden className="size-4 text-ink-3" />
                  <h2 className="text-sm font-semibold">{title}</h2>
                </div>
                <p className="mt-1 flex-1 text-[13px] text-ink-3">{text}</p>
                {reason ? (
                  <p className="mt-4 text-[13px] text-ink-3">{reason}</p>
                ) : (
                  <a href={api.reportUrl(productId, id)} className={buttonClasses({ variant: 'secondary', className: 'mt-4 self-start' })}>
                    Download {id.toUpperCase()}
                  </a>
                )}
              </div>
            )
          })}
        </div>
      </Panel>
    </>
  )
}

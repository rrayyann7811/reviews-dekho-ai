import { FileText, Table2 } from 'lucide-react'
import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ServerNotice from '../components/ServerNotice'
import { buttonClasses } from '../components/ui/buttonStyles'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import { api } from '../lib/api'
import { useServerStatus } from '../lib/serverStatus'
import { useProducts } from '../lib/useData'

const FORMATS = [
  { id: 'pdf', icon: FileText, title: 'PDF report', text: 'A printable summary: key figures, charts, strengths, complaints and example reviews.' },
  { id: 'csv', icon: Table2, title: 'CSV export', text: 'Every review with its sentiment label, score and detected features, for use in Excel.' },
]

export default function Reports() {
  const { items } = useProducts()
  const { status } = useServerStatus()
  const [productId, setProductId] = useState('')
  const ready = status === 'online' && productId

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
          {FORMATS.map(({ id, icon: Icon, title, text }) => (
            <div key={id} className="flex flex-col rounded-lg border border-line p-4">
              <div className="flex items-center gap-2">
                <Icon aria-hidden className="size-4 text-ink-3" />
                <h2 className="text-sm font-semibold">{title}</h2>
              </div>
              <p className="mt-1 flex-1 text-[13px] text-ink-3">{text}</p>
              {ready ? (
                <a href={api.reportUrl(productId, id)} className={buttonClasses({ variant: 'secondary', className: 'mt-4 self-start' })}>
                  Download {id.toUpperCase()}
                </a>
              ) : (
                <p className="mt-4 text-[13px] text-ink-3">
                  {status !== 'online' ? 'Available when the server is running.' : 'Choose a product first.'}
                </p>
              )}
            </div>
          ))}
        </div>
      </Panel>
    </>
  )
}

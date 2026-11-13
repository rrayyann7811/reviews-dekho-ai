import { Columns2 } from 'lucide-react'
import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ServerNotice from '../components/ServerNotice'
import Alert from '../components/ui/Alert'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import { useProducts } from '../lib/useData'

function ProductSelect({ items, label, value, onChange, exclude }) {
  return (
    <Field label={label}>
      {(props) => (
        <Select {...props} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose a product…</option>
          {items.filter((p) => p.id !== exclude).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </Select>
      )}
    </Field>
  )
}

export default function Compare() {
  const { items } = useProducts()
  const [a, setA] = useState('')
  const [b, setB] = useState('')

  return (
    <>
      <PageHeader title="Compare products" description="Put two analysed products side by side: ratings, sentiment and the features customers mention most." />
      <ServerNotice feature="Comparing products" />

      {items.length < 2 ? (
        <Panel>
          <EmptyState icon={Columns2} title="You need at least two analysed products"
            action={<Button to="/upload">Upload reviews</Button>}>
            {items.length === 1
              ? `So far only “${items[0].name}” has been analysed. Add another product to compare it with.`
              : 'Analyse two products first, then come back here.'}
          </EmptyState>
        </Panel>
      ) : (
        <Panel title="Choose two products">
          <div className="grid gap-4 sm:grid-cols-2">
            <ProductSelect items={items} label="Product A" value={a} onChange={setA} exclude={b} />
            <ProductSelect items={items} label="Product B" value={b} onChange={setB} exclude={a} />
          </div>
          {a && b && (
            <Alert className="mt-5" title="Side-by-side comparison is part of Phase 7">
              Product selection works; the comparison view is built in a later phase.
            </Alert>
          )}
        </Panel>
      )}
    </>
  )
}

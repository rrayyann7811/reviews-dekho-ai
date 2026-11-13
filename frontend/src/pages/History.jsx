import { History as HistoryIcon, Search } from 'lucide-react'
import { useState } from 'react'
import PageHeader from '../components/layout/PageHeader'
import ProductTable from '../components/ProductTable'
import Alert from '../components/ui/Alert'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { Input, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import Spinner from '../components/ui/Spinner'
import { useProducts } from '../lib/useData'

export default function History() {
  const { items, loading, error, serverOffline } = useProducts()
  const [query, setQuery] = useState('')
  const [source, setSource] = useState('all')

  const q = query.trim().toLowerCase()
  const visible = items
    .filter((p) => source === 'all' || p.source === source)
    .filter((p) => !q || `${p.name} ${p.brand ?? ''} ${p.category ?? ''}`.toLowerCase().includes(q))
    .sort((a, b) => (b.analyzedAt ?? '').localeCompare(a.analyzedAt ?? ''))

  return (
    <>
      <PageHeader title="Analysis history" description="Every product you have analysed. Select a row to open its analysis." />
      {serverOffline && (
        <Alert variant="warning" className="mb-6" title="Showing the demo product only">
          The analysis server isn’t running, so saved analyses can’t be loaded.
        </Alert>
      )}
      {error && <Alert variant="error" className="mb-6" title="Couldn’t load saved analyses">{error.message}</Alert>}

      <Panel bodyClassName="">
        <div className="flex flex-col gap-2 border-b border-line px-5 py-3 sm:flex-row">
          <div className="relative flex-1">
            <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-3" />
            <Input aria-label="Search products" placeholder="Search by product name" className="pl-9" value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <Select aria-label="Filter by source" className="sm:w-48" value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="all">All sources</option>
            <option value="upload">Uploaded files</option>
            <option value="url">Product links</option>
            <option value="demo">Demo data</option>
          </Select>
        </div>
        {loading && items.length === 0 ? (
          <div className="px-5 py-8"><Spinner /></div>
        ) : items.length === 0 ? (
          <EmptyState icon={HistoryIcon} title="No analyses yet" action={<Button to="/upload">Upload reviews</Button>}>
            Products you analyse will be listed here.
          </EmptyState>
        ) : visible.length === 0 ? (
          <EmptyState title="No products match your search" action={<Button variant="secondary" onClick={() => { setQuery(''); setSource('all') }}>Clear filters</Button>} />
        ) : (
          <ProductTable products={visible} />
        )}
      </Panel>
    </>
  )
}

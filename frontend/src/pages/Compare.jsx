import { Columns2, RotateCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { FeatureCompare } from '../components/compare/FeatureCompare'
import { RatingCompare, SentimentCompare } from '../components/compare/Charts'
import { CaveatList, SideCard, Statements } from '../components/compare/Overview'
import { SideTag } from '../components/compare/parts'
import PageHeader from '../components/layout/PageHeader'
import RunSelect from '../components/RunSelect'
import ServerNotice from '../components/ServerNotice'
import Alert from '../components/ui/Alert'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import { Field, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import Spinner from '../components/ui/Spinner'
import { DEMO_ID } from '../demo/demo'
import { api } from '../lib/api'
import { useServerStatus } from '../lib/serverStatus'
import { useProducts } from '../lib/useData'
import { useRuns } from '../lib/useRuns'

// The selection lives in the URL (?a=1&ra=5&b=2&rb=), so a comparison can be shared, bookmarked and reached with Back.
const KEYS = { a: ['a', 'ra'], b: ['b', 'rb'] }

function ProductSelect({ side, products, value, onChange }) {
  return (
    <Field label={`Product ${side.toUpperCase()}`}>
      {(props) => (
        <Select {...props} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">Choose a product…</option>
          {products.map((p) => (
            <option key={p.id} value={String(p.id)} disabled={!p.analyzedAt}>
              {p.name}{p.analyzedAt ? '' : ' (not analysed yet)'}
            </option>
          ))}
        </Select>
      )}
    </Field>
  )
}

function SidePicker({ side, products, productId, runId, onProduct, onRun, enabled }) {
  const runs = useRuns(productId, enabled && !!productId)
  return (
    <fieldset className="min-w-0 space-y-3">
      <legend className="mb-3 flex items-center gap-2 text-[13px] font-semibold text-ink"><SideTag side={side} /> Side {side.toUpperCase()}</legend>
      <ProductSelect side={side} products={products} value={productId} onChange={onProduct} />
      {runs.error && <p className="text-[13px] text-neg">{runs.error}</p>}
      {runs.items.length > 0 && (
        <RunSelect label={`Run for side ${side.toUpperCase()}`} runs={runs.items}
          value={runs.items[0]?.id === Number(runId) ? '' : runId} onChange={onRun}
          hint={runs.items.length > 1 ? `${runs.items.length} saved runs` : 'Only one saved run'} />
      )}
    </fieldset>
  )
}

/** Loads the comparison for the current selection. */
function useComparison(selection, enabled) {
  const key = JSON.stringify(selection)
  const [state, setState] = useState({ key: null, data: null, error: null })
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    if (!enabled) return
    let active = true
    api.compare(JSON.parse(key))
      .then((data) => active && setState({ key, data, error: null }))
      .catch((error) => active && setState({ key, data: null, error }))
    return () => { active = false }
  }, [key, enabled, attempt])
  const current = state.key === key
  return { data: current ? state.data : null, error: current ? state.error : null, loading: enabled && !current,
    retry: () => { setState({ key: null, data: null, error: null }); setAttempt((n) => n + 1) } }
}

export default function Compare() {
  const { status } = useServerStatus()
  const { items, loading: productsLoading, error: productsError } = useProducts()
  const [params, setParams] = useSearchParams()
  const products = items.filter((p) => p.id !== DEMO_ID)
  const online = status === 'online'
  const selected = { a: params.get('a') ?? '', ra: params.get('ra') ?? '', b: params.get('b') ?? '', rb: params.get('rb') ?? '' }
  const ready = online && !!selected.a && !!selected.b
  const comparison = useComparison({ productA: selected.a, productB: selected.b, analysisA: selected.ra || undefined,
    analysisB: selected.rb || undefined }, ready)

  const update = (changes) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(changes)) {
      if (v) next.set(k, v)
      else next.delete(k)
    }
    setParams(next)
  }
  const pick = (side) => (productId) => update({ [KEYS[side][0]]: productId, [KEYS[side][1]]: '' })
  const pickRun = (side) => (runId) => update({ [KEYS[side][1]]: runId })

  let body = null
  if (status === 'offline') {
    body = (
      <Panel>
        <EmptyState icon={Columns2} title="Comparing needs the analysis server">
          The comparison is computed from saved analysis runs on the server. The built-in demo product can’t be compared.
        </EmptyState>
      </Panel>
    )
  } else if (status === 'checking' || productsLoading) {
    body = <Spinner label="Loading products…" />
  } else if (productsError) {
    body = <Alert variant="error" title="Couldn’t load the products">{productsError.message}</Alert>
  } else if (products.filter((p) => p.analyzedAt).length === 0) {
    body = (
      <Panel>
        <EmptyState icon={Columns2} title="No analysed products yet" action={<Button to="/upload">Upload reviews</Button>}>
          Analyse a product first. You can then compare two products, or two analysis runs of the same product.
        </EmptyState>
      </Panel>
    )
  } else {
    body = (
      <>
        <Panel title="Choose what to compare"
          description="Pick two products, or the same product twice with different runs to see how it changed. Each run is a saved snapshot.">
          <div className="grid gap-6 md:grid-cols-2">
            <SidePicker side="a" products={products} productId={selected.a} runId={selected.ra} enabled={online}
              onProduct={pick('a')} onRun={pickRun('a')} />
            <SidePicker side="b" products={products} productId={selected.b} runId={selected.rb} enabled={online}
              onProduct={pick('b')} onRun={pickRun('b')} />
          </div>
          {products.filter((p) => p.analyzedAt).length === 1 && (
            <p className="mt-4 text-[13px] text-ink-3">Only one product has been analysed so far: choose it on both sides and pick an earlier run on one of them.</p>
          )}
        </Panel>
        {ready && <ComparisonView comparison={comparison} />}
      </>
    )
  }

  return (
    <>
      <PageHeader title="Compare products"
        description="Two saved analysis runs side by side: tone, star ratings and features, with the sample sizes and caveats behind every difference." />
      <ServerNotice feature="Comparing products" />
      <div className="space-y-6">{body}</div>
    </>
  )
}

function ComparisonView({ comparison }) {
  const { data, error, loading, retry } = comparison
  if (loading) return <Spinner label="Comparing…" />
  if (error) {
    return (
      <Alert variant="error" title="Couldn’t compare these runs"
        action={<Button variant="secondary" size="sm" onClick={retry}><RotateCw aria-hidden className="size-3.5" /> Try again</Button>}>
        {error.message}
      </Alert>
    )
  }
  if (!data) return null
  return (
    <div className="space-y-6" aria-live="polite">
      <div className="grid gap-4 md:grid-cols-2">
        <SideCard side="a" data={data.a} />
        <SideCard side="b" data={data.b} />
      </div>
      <CaveatList caveats={data.caveats} />
      <Statements statements={data.statements} notes={data.notes} />
      {!data.sameRun && (
        <>
          <SentimentCompare comparison={data} />
          <RatingCompare comparison={data} />
          <FeatureCompare features={data.features} />
        </>
      )}
    </div>
  )
}

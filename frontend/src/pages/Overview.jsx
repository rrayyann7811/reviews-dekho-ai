import { ArrowRight, Columns2, X } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import ProductTable from '../components/ProductTable'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Panel from '../components/ui/Panel'
import Spinner from '../components/ui/Spinner'
import UrlForm from '../components/UrlForm'
import { useSettings } from '../lib/settings'
import { useProducts } from '../lib/useData'

const STEPS = [
  { title: 'Add reviews', text: 'Paste a product link from a supported website, or upload a CSV/Excel file of reviews.' },
  { title: 'Let the app analyse them', text: 'Each review is scored as positive, neutral or negative, and product features like battery or delivery are picked out.' },
  { title: 'Explore and compare', text: 'See what customers like and dislike, read the reviews behind each number, and compare two products.' },
]

function GettingStarted({ onDismiss }) {
  return (
    <section className="mb-6 rounded-lg border border-line bg-surface">
      <div className="flex items-center justify-between border-b border-line px-5 py-3">
        <h2 className="text-sm font-semibold">How it works</h2>
        <button type="button" onClick={onDismiss} className="flex items-center gap-1 rounded-md px-2 py-1 text-[13px] text-ink-3 hover:bg-black/[0.04] hover:text-ink">
          <X aria-hidden className="size-3.5" /> Hide
        </button>
      </div>
      <ol className="grid divide-y divide-line md:grid-cols-3 md:divide-x md:divide-y-0">
        {STEPS.map((step, i) => (
          <li key={step.title} className="flex gap-3 px-5 py-4">
            <span className="flex size-6 shrink-0 items-center justify-center rounded-full border border-line-strong text-xs font-medium tabular-nums text-ink-2">{i + 1}</span>
            <div>
              <p className="text-sm font-medium text-ink">{step.title}</p>
              <p className="mt-0.5 text-[13px] text-ink-3">{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function Overview() {
  const { settings, update } = useSettings()
  const { items, loading } = useProducts()
  const recent = [...items].sort((a, b) => (b.analyzedAt ?? '').localeCompare(a.analyzedAt ?? '')).slice(0, 5)

  return (
    <>
      <PageHeader title="Overview" description="Find out what customers think of a product from its reviews." />

      {!settings.introDismissed && <GettingStarted onDismiss={() => update({ introDismissed: true })} />}

      <div className="mb-6 grid gap-6 lg:grid-cols-5">
        <Panel title="Analyze a product link" description="Supported: Demo store. Amazon and Flipkart links are recognised but can’t be collected." className="lg:col-span-3">
          <UrlForm compact />
        </Panel>
        <Panel title="Upload a review file" description="Works with reviews from any website." className="lg:col-span-2">
          <p className="text-[13px] text-ink-2">
            Upload a CSV or Excel file with one review per row. You’ll see a preview and can confirm which column holds the review text before anything is analysed.
          </p>
          <Button to="/upload" variant="secondary" className="mt-4">Upload reviews</Button>
        </Panel>
      </div>

      <Panel
        title="Recent analyses"
        bodyClassName=""
        actions={items.length > 0 && <Button to="/history" variant="ghost" size="sm">View all <ArrowRight aria-hidden className="size-3.5" /></Button>}
      >
        {loading && items.length === 0 ? (
          <div className="px-5 py-8"><Spinner /></div>
        ) : recent.length === 0 ? (
          <EmptyState title="No products analysed yet">Analyse a product link or upload a review file to get started.</EmptyState>
        ) : (
          <ProductTable products={recent} />
        )}
      </Panel>

      <div className="mt-6 flex flex-col gap-4 rounded-lg border border-line bg-surface px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-3">
          <Columns2 aria-hidden className="mt-0.5 size-5 shrink-0 text-ink-3" />
          <div>
            <p className="text-sm font-medium">Compare two products</p>
            <p className="text-[13px] text-ink-3">See ratings, sentiment and the most praised and criticised features side by side.</p>
          </div>
        </div>
        <Button to="/compare" variant="secondary">Compare products</Button>
      </div>
    </>
  )
}

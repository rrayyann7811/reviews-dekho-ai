import { Columns2 } from 'lucide-react'
import { useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import AspectTable from '../components/analysis/AspectTable'
import DistributionCharts from '../components/analysis/DistributionCharts'
import ReviewExplorer from '../components/analysis/ReviewExplorer'
import StatStrip from '../components/analysis/StatStrip'
import SummaryPanel from '../components/analysis/SummaryPanel'
import HBarChart from '../components/charts/HBarChart'
import PageHeader from '../components/layout/PageHeader'
import Alert from '../components/ui/Alert'
import { SourceBadge } from '../components/ui/Badge'
import Button from '../components/ui/Button'
import EmptyState from '../components/ui/EmptyState'
import Panel from '../components/ui/Panel'
import Spinner from '../components/ui/Spinner'
import Tabs from '../components/ui/Tabs'
import { formatDate, plural } from '../lib/format'
import { DEFAULT_FILTERS } from '../lib/reviewFilters'
import { useAnalysis } from '../lib/useData'

const BACK = { to: '/history', label: 'Analysis history' }

function DataSourceNote({ data }) {
  if (data.product.source === 'demo') {
    return (
      <Alert variant="warning" title="Demo data" className="mb-6">
        These {data.stats.totalReviews} reviews are synthetic. They were written to demonstrate the app and are not real customer
        reviews, and the product is fictional. Everything below is calculated from them by the same analysis used for real data.
      </Alert>
    )
  }
  return null
}

function AspectsTab({ data, onOpenReview }) {
  return (
    <div className="space-y-6">
      <Panel title="Product features" bodyClassName=""
        description="How reviews talk about each feature. A review counts once per feature, scored on the phrase that mentions it.">
        {data.aspects.length ? (
          <AspectTable aspects={data.aspects} onOpenReview={onOpenReview} />
        ) : (
          <EmptyState title="No known features were mentioned">Feature detection looks for words like battery, camera, price or delivery.</EmptyState>
        )}
        <p className="border-t border-line px-5 py-3 text-[13px] text-ink-3">
          “Overall” needs at least 3 mentions, and 65% of them in one direction; otherwise it shows Mixed.
        </p>
      </Panel>
      <Panel title="Frequently mentioned words" description="Words and two-word phrases ranked by how many reviews use them. Common words like “the” or “phone” are ignored.">
        {data.keywords.length ? (
          <HBarChart
            data={data.keywords.map((k) => ({ label: k.term, value: k.reviews }))}
            labelWidth={120}
            rowHeight={28}
            ariaLabel={`Top keywords: ${data.keywords.map((k) => `${k.term} (${k.reviews})`).join(', ')}`}
            valueLabel={(d) => `${d.value} reviews`}
            describe={(d) => `Used in ${plural(d.value, 'review')} of ${data.stats.totalReviews}`}
          />
        ) : (
          <p className="text-[13px] text-ink-3">Not enough reviews to find repeated words.</p>
        )}
      </Panel>
    </div>
  )
}

export default function ProductAnalysis() {
  const { productId } = useParams()
  const { data, loading, error } = useAnalysis(productId)
  const [params, setParams] = useSearchParams()
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [focus, setFocus] = useState(null)

  const tab = ['overview', 'reviews', 'aspects'].includes(params.get('tab')) ? params.get('tab') : 'overview'
  const setTab = (value) => setParams(value === 'overview' ? {} : { tab: value }, { replace: true })

  function openReview(id) {
    setFilters(DEFAULT_FILTERS)
    setFocus({ id, seq: Date.now() })
    setTab('reviews')
  }

  function showMismatches() {
    setFilters({ ...DEFAULT_FILTERS, sentiment: 'mismatch' })
    setTab('reviews')
  }

  if (loading) return <Spinner label="Loading analysis…" />
  if (error) {
    return (
      <>
        <PageHeader title="Analysis" back={BACK} />
        <Alert variant="error" title={error.status === 404 ? 'This product doesn’t exist' : 'Couldn’t load this analysis'}>
          {error.status === 404 ? 'It may have been deleted. Choose another product from your history.' : error.message}
        </Alert>
      </>
    )
  }

  const { product, stats } = data
  return (
    <>
      <PageHeader
        title={product.name}
        back={BACK}
        meta={
          <>
            <SourceBadge source={product.source} />
            <span className="text-[13px] text-ink-3">
              {[product.brand, product.category].filter(Boolean).join(' · ')}
              {stats.dateRange && ` · Reviews from ${formatDate(stats.dateRange.from)} to ${formatDate(stats.dateRange.to)}`}
            </span>
          </>
        }
        actions={<Button to="/compare" variant="secondary"><Columns2 aria-hidden className="size-4" /> Compare</Button>}
      />
      <DataSourceNote data={data} />

      <Tabs
        label="Analysis sections"
        value={tab}
        onChange={setTab}
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'reviews', label: 'Reviews', count: stats.totalReviews },
          { value: 'aspects', label: 'Features & keywords' },
        ]}
      />

      <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="pt-6">
        {tab === 'overview' && (
          <div className="space-y-6">
            <StatStrip stats={stats} ingestion={data.ingestion} />
            <DistributionCharts stats={stats} onShowMismatches={showMismatches} />
            <SummaryPanel summary={data.summary} onOpenReview={openReview} />
            <p className="text-xs text-ink-3">
              Sentiment is estimated from the wording with VADER, a rule-based method. It can misread sarcasm and very short reviews.
              Analysed {formatDate(data.analyzedAt)}.
            </p>
          </div>
        )}
        {tab === 'reviews' && (
          <ReviewExplorer reviews={data.reviews} mismatchIds={stats.ratingSentimentMismatches}
            filters={filters} onFiltersChange={setFilters} focus={focus} />
        )}
        {tab === 'aspects' && <AspectsTab data={data} onOpenReview={openReview} />}
      </div>
    </>
  )
}

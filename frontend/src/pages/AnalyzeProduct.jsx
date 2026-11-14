import { CheckCircle2, CircleSlash } from 'lucide-react'
import PageHeader from '../components/layout/PageHeader'
import ServerNotice from '../components/ServerNotice'
import Panel from '../components/ui/Panel'
import UrlForm from '../components/UrlForm'
import { SITES } from '../lib/sites'
import { STATIC_DEMO } from '../lib/staticDemo'

// In the online demo only the demo store's link works (it opens the built-in demo product).
function siteLabel(site) {
  if (site.status !== 'supported') return 'Recognised only'
  if (!STATIC_DEMO) return 'Supported'
  return site.id === 'demo' ? 'Opens the demo product' : 'Supported in the full app'
}

export default function AnalyzeProduct() {
  return (
    <>
      <PageHeader
        title="Analyze a product link"
        description="Paste a link to a product page. If the website is supported, its reviews are collected and analysed."
      />
      {STATIC_DEMO && <ServerNotice feature="Collecting reviews from links" />}
      <div className="grid items-start gap-6 lg:grid-cols-5">
        <Panel title="Product link" className="lg:col-span-3">
          <UrlForm />
        </Panel>

        <Panel title="Supported websites" bodyClassName="" className="lg:col-span-2">
          <ul className="divide-y divide-line">
            {SITES.map((site) => (
              <li key={site.id} className="flex gap-3 px-5 py-3.5">
                {site.status === 'supported' && !(STATIC_DEMO && site.id !== 'demo') ? (
                  <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-pos" />
                ) : (
                  <CircleSlash aria-hidden className="mt-0.5 size-4 shrink-0 text-ink-3" />
                )}
                <div className="min-w-0">
                  <p className="text-sm font-medium">
                    {site.name}
                    <span className="ml-2 text-xs font-normal text-ink-3">{siteLabel(site)}</span>
                  </p>
                  <p className="mt-0.5 text-[13px] text-ink-3">{site.note}</p>
                </div>
              </li>
            ))}
          </ul>
          <p className="border-t border-line px-5 py-3.5 text-[13px] text-ink-3">
            Reviews are only collected through permitted sources. For any other website, upload the reviews as a CSV or Excel file.
          </p>
        </Panel>
      </div>
    </>
  )
}

import PageHeader from '../components/layout/PageHeader'
import Button from '../components/ui/Button'
import Panel from '../components/ui/Panel'
import { api } from '../lib/api'
import { useServerStatus } from '../lib/serverStatus'
import { useSettings } from '../lib/settings'

const STATUS_TEXT = { online: 'Connected', offline: 'Not reachable', checking: 'Checking…' }

function Row({ label, children }) {
  return (
    <div className="flex flex-col gap-1 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <dt className="text-sm text-ink-2">{label}</dt>
      <dd className="text-sm text-ink">{children}</dd>
    </div>
  )
}

export default function Settings() {
  const { status, check } = useServerStatus()
  const { settings, update } = useSettings()

  return (
    <>
      <PageHeader title="Settings" />
      <div className="max-w-3xl space-y-6">
        <Panel title="Analysis server" bodyClassName="px-5">
          <dl className="divide-y divide-line">
            <Row label="Address"><code className="text-[13px]">{api.baseUrl}</code></Row>
            <Row label="Status">
              <span className="flex items-center gap-3">
                {STATUS_TEXT[status]}
                <Button variant="secondary" size="sm" onClick={check} disabled={status === 'checking'}>Check again</Button>
              </span>
            </Row>
          </dl>
        </Panel>

        <Panel title="Demo data" bodyClassName="px-5">
          <label className="flex cursor-pointer items-start justify-between gap-6 py-3.5">
            <span>
              <span className="block text-sm text-ink">Show the demo product</span>
              <span className="mt-0.5 block text-[13px] text-ink-3">
                Lists the sample product (synthetic reviews) alongside your own analyses. It’s always labelled “Demo data”.
              </span>
            </span>
            <input type="checkbox" className="mt-1 size-4 shrink-0 cursor-pointer accent-brand-600" checked={settings.showDemo}
              onChange={(e) => update({ showDemo: e.target.checked })} />
          </label>
          <div className="flex items-center justify-between gap-6 border-t border-line py-3.5">
            <span className="text-sm text-ink">“How it works” guide on the Overview page</span>
            <Button variant="secondary" size="sm" disabled={!settings.introDismissed} onClick={() => update({ introDismissed: false })}>
              {settings.introDismissed ? 'Show again' : 'Showing'}
            </Button>
          </div>
        </Panel>

        <Panel title="How the analysis works">
          <dl className="space-y-4 text-[13px]">
            <div>
              <dt className="font-medium text-ink">Sentiment</dt>
              <dd className="mt-0.5 text-ink-3">Each review is scored with VADER, a rule-based method that uses a dictionary of positive and negative words. Scores range from −1 to +1; above +0.05 is positive, below −0.05 negative, anything in between neutral. It can misread sarcasm and very short reviews.</dd>
            </div>
            <div>
              <dt className="font-medium text-ink">Product features</dt>
              <dd className="mt-0.5 text-ink-3">Reviews are split into short phrases. A phrase that mentions a feature word (for example “battery” or “charging”) is scored on its own, so one review can praise one feature and criticise another.</dd>
            </div>
            <div>
              <dt className="font-medium text-ink">Star ratings</dt>
              <dd className="mt-0.5 text-ink-3">Star ratings are reported separately from the text. Reviews whose stars and wording disagree are flagged rather than hidden.</dd>
            </div>
          </dl>
        </Panel>
      </div>
    </>
  )
}

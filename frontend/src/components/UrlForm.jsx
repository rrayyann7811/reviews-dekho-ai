import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DEMO_ID } from '../demo/demo'
import { api } from '../lib/api'
import { useServerStatus } from '../lib/serverStatus'
import { DEMO_PRODUCT_PATH, SITES, detectSite, parseProductUrl } from '../lib/sites'
import Alert from './ui/Alert'
import Button from './ui/Button'
import { Field, Input } from './ui/Field'

const DEMO_URL = SITES.find((s) => s.id === 'demo').example

function Outcome({ outcome }) {
  const alternatives = (
    <div className="flex flex-wrap gap-2">
      <Button to="/upload" variant="secondary" size="sm">Upload a review file</Button>
      <Button to={`/products/${DEMO_ID}`} variant="ghost" size="sm">Open the demo product</Button>
    </div>
  )
  if (outcome.kind === 'unavailable') {
    return (
      <Alert variant="warning" title={`${outcome.site.name} reviews can’t be collected automatically`} action={alternatives}>
        {outcome.site.name} doesn’t offer a public way to access its reviews, and this app doesn’t scrape websites
        against their terms. If you have the reviews as a CSV or Excel file (for example, exported by the seller),
        upload them instead.
      </Alert>
    )
  }
  if (outcome.kind === 'unsupported') {
    return (
      <Alert variant="warning" title={`${outcome.host} isn’t supported yet`} action={alternatives}>
        Reviews can only be collected from the websites listed below. You can still analyse reviews from any
        website by uploading them as a file.
      </Alert>
    )
  }
  if (outcome.kind === 'demo-not-found') {
    return (
      <Alert variant="warning" title="No demo product at this address">
        The demo store has one product. Use <span className="font-medium break-all">{DEMO_URL}</span>.
      </Alert>
    )
  }
  return <Alert variant="error" title="Couldn’t analyse this link">{outcome.message}</Alert>
}

export default function UrlForm({ compact = false }) {
  const navigate = useNavigate()
  const { status } = useServerStatus()
  const [value, setValue] = useState('')
  const [error, setError] = useState('')
  const [outcome, setOutcome] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setOutcome(null)
    const { url, error: validationError } = parseProductUrl(value)
    if (validationError) return setError(validationError)
    setError('')

    const site = detectSite(url)
    if (site?.id === 'demo') {
      return url.pathname.replace(/\/$/, '') === DEMO_PRODUCT_PATH
        ? navigate(`/products/${DEMO_ID}`)
        : setOutcome({ kind: 'demo-not-found' })
    }
    if (site?.status === 'unavailable') return setOutcome({ kind: 'unavailable', site })
    if (status !== 'online') return setOutcome({ kind: 'unsupported', host: url.hostname.replace(/^www\./, '') })

    // Unknown website: the backend's adapter list is the final authority.
    setLoading(true)
    try {
      const product = await api.analyzeUrl(url.href)
      navigate(`/products/${product.id}`)
    } catch (err) {
      setOutcome(err.status === 422 ? { kind: 'unsupported', host: url.hostname } : { kind: 'error', message: err.message })
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <Field label="Product link" hideLabel={compact} error={error} className="flex-1"
          hint={compact ? undefined : 'Paste the full address of a product page.'}>
          {(props) => (
            <Input
              {...props}
              type="url"
              inputMode="url"
              autoComplete="off"
              placeholder="https://www.example.com/product/…"
              value={value}
              invalid={!!error}
              onChange={(e) => setValue(e.target.value)}
            />
          )}
        </Field>
        <Button type="submit" disabled={loading} className={compact ? '' : 'sm:mt-[26px]'}>
          {loading ? 'Analysing…' : 'Analyze'}
        </Button>
      </form>
      {outcome && <Outcome outcome={outcome} />}
      <p className="text-[13px] text-ink-3">
        No link handy?{' '}
        <button type="button" className="font-medium text-brand-600 hover:underline" onClick={() => { setValue(DEMO_URL); setError('') }}>
          Use the demo product link
        </button>
      </p>
    </div>
  )
}

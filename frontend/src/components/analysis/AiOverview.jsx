import { Sparkles } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../../lib/api'
import Alert from '../ui/Alert'
import Button from '../ui/Button'
import Panel from '../ui/Panel'
import Spinner from '../ui/Spinner'

/**
 * Optional AI-written overview (off unless the backend runs with AI_SUMMARIES=on).
 * Always shown below the evidence-backed summary, never instead of it.
 */
export default function AiOverview({ productId, analysisId, onOpenReview }) {
  const [status, setStatus] = useState(null)
  const [state, setState] = useState({ loading: true, attempt: null, busy: false, error: '' })

  useEffect(() => {
    let active = true
    api.aiStatus().then((s) => {
      if (!active) return
      setStatus(s)
      if (!s.enabled) return
      api.getAiSummary(productId, analysisId)
        .then((attempt) => active && setState((st) => ({ ...st, loading: false, attempt })))
        .catch((err) => active && setState((st) => ({ ...st, loading: false, error: err.message })))
    }).catch(() => active && setStatus({ enabled: false }))
    return () => { active = false }
  }, [productId, analysisId])

  if (!status?.enabled) return null // turned off: nothing to show

  async function write() {
    setState((st) => ({ ...st, busy: true, error: '' }))
    try {
      const attempt = await api.createAiSummary(productId, analysisId)
      setState((st) => ({ ...st, busy: false, attempt }))
    } catch (err) {
      setState((st) => ({ ...st, busy: false, error: err.message }))
    }
  }

  const { attempt } = state
  const refs = attempt?.references ?? {}
  return (
    <Panel title={<span className="inline-flex items-center gap-2"><Sparkles aria-hidden className="size-4 text-brand-600" />AI-written overview (optional)</span>}
      description={`Written by ${status.model} running on this computer, from the evidence-backed summary above. Each sentence cites its evidence and is checked automatically.`}>
      {state.loading ? <Spinner label="Loading…" /> : (
        <div className="space-y-4">
          {attempt?.status === 'accepted' && (
            <div className="space-y-2">
              {attempt.sentences.map((sentence, i) => (
                <p key={i} className="text-sm leading-relaxed text-ink">
                  {sentence.text}{' '}
                  {sentence.claims.map((c) => (
                    <span key={c} className="mr-1 inline-flex rounded bg-subtle px-1.5 text-[11px] text-ink-3" title="Claim in the summary">{refs[c] ?? c}</span>
                  ))}
                  {sentence.excerpts.map((e) => (
                    <button key={e} type="button" onClick={() => onOpenReview(refs[e])}
                      className="mr-1 inline-flex rounded bg-brand-50 px-1.5 text-[11px] text-brand-700 hover:underline">
                      Review {refs[e] ?? e}
                    </button>
                  ))}
                </p>
              ))}
              <p className="text-xs text-ink-3">{attempt.label}</p>
            </div>
          )}
          {attempt?.status === 'rejected' && (
            <Alert variant="warning" title="The AI text didn’t pass the checks, so it isn’t shown">
              Only the evidence-backed summary above is used. What the checker found:
              <ul className="mt-1 list-disc pl-5">{attempt.problems.slice(0, 5).map((p) => <li key={p}>{p}</li>)}</ul>
            </Alert>
          )}
          {state.error && <Alert variant="error" title="Couldn’t write the AI overview">{state.error}</Alert>}
          {!status.available && !attempt && <p className="text-[13px] text-ink-3">{status.reason}</p>}
          {status.available && (
            state.busy ? <Spinner label="The local model is writing… this can take a minute." /> : (
              <Button variant="secondary" size="sm" onClick={write}>
                <Sparkles aria-hidden className="size-3.5" /> {attempt ? 'Write again' : 'Write an AI overview'}
              </Button>
            )
          )}
        </div>
      )}
    </Panel>
  )
}

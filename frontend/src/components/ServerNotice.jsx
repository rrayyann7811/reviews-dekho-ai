import { useServerStatus } from '../lib/serverStatus'
import { STATIC_DEMO, STATIC_DEMO_MESSAGE } from '../lib/staticDemo'
import Alert from './ui/Alert'
import Button from './ui/Button'

/** Explains, where it matters, that a feature needs the backend running. */
export default function ServerNotice({ feature, className = 'mb-6' }) {
  const { status, check } = useServerStatus()
  if (status !== 'offline') return null
  if (STATIC_DEMO) {
    return <Alert variant="info" title={`${feature} isn’t available in the online demo`} className={className}>{STATIC_DEMO_MESSAGE}</Alert>
  }
  return (
    <Alert
      variant="warning"
      title="The analysis server isn’t running"
      className={className}
      action={<Button variant="secondary" size="sm" onClick={check}>Check again</Button>}
    >
      {feature} needs the backend. Start it from the <code className="rounded bg-black/5 px-1">backend</code> folder with{' '}
      <code className="rounded bg-black/5 px-1">.venv/bin/uvicorn app.main:app --reload</code>. The demo product still works without it.
    </Alert>
  )
}

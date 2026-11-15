import { useEffect, useRef, useState } from 'react'
import Button from './ui/Button'
import { Field, Input } from './ui/Field'
import Panel from './ui/Panel'

export default function AccountActions({ provider, recovery = false, onCancel }) {
  const [mode, setMode] = useState(recovery ? 'recovery' : '')
  const [state, setState] = useState({ busy: false, error: '', message: '' })
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  if (!provider?.register || !provider?.requestPasswordReset || !provider?.updatePassword) return null
  async function submit(event) {
    event.preventDefault()
    if (state.busy) return
    const form = event.currentTarget, data = new FormData(form)
    const email = data.get('email'), password = data.get('password')
    form.reset()
    setState({ busy: true, error: '', message: '' })
    try {
      const message = mode === 'register' ? await provider.register({ email, password })
        : mode === 'reset' ? await provider.requestPasswordReset(email) : await provider.updatePassword(password)
      if (alive.current) setState({ busy: false, error: '', message: message || 'Password updated. Sign in again.' })
    } catch {
      if (alive.current) setState({ busy: false, message: '', error: 'The account request could not be completed. Try again or request a new email link.' })
    }
  }
  if (!mode) return <div className="flex flex-wrap gap-3">
    <Button variant="secondary" onClick={() => setMode('register')}>Create an account</Button>
    <Button variant="secondary" onClick={() => setMode('reset')}>Forgot password?</Button>
  </div>
  return <Panel title={mode === 'register' ? 'Create an account' : mode === 'reset' ? 'Request a password reset' : 'Choose a new password'}>
    <form onSubmit={submit} className="space-y-4" aria-busy={state.busy}>
      {mode !== 'recovery' && <Field label="Account email">{(props) => <Input {...props} type="email" name="email" autoComplete="email" required disabled={state.busy} />}</Field>}
      {mode !== 'reset' && <Field label="New password" hint="Use a unique password of at least 12 characters.">{(props) => <Input {...props} type="password" name="password" autoComplete="new-password" required minLength={12} disabled={state.busy} />}</Field>}
      {state.error && <p role="alert" className="text-sm text-neg">{state.error}</p>}
      {state.message && <p role="status" className="text-sm text-ink-2">{state.message}</p>}
      <Button type="submit" disabled={state.busy}>{state.busy ? 'Please wait…' : mode === 'register' ? 'Register' : mode === 'reset' ? 'Send reset link' : 'Update password'}</Button>
      <Button variant="secondary" disabled={state.busy} onClick={() => {
        if (recovery) onCancel()
        else { setMode(''); setState({ busy: false, message: '', error: '' }) }
      }}>{recovery ? 'Cancel and sign out' : 'Back to sign-in'}</Button>
    </form>
  </Panel>
}

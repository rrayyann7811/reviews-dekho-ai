import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import HostedApp from '../components/HostedApp'
import App from '../App'
import { deferred, fakeProvider, fakeSession } from './helpers/fakeIdentity'
import { setAccessTokenProvider } from '../lib/api'

function provider(session = null) {
  return Object.assign(fakeProvider(session), {
    register: vi.fn(async () => 'If registration is available, check your email to confirm your account.'),
    requestPasswordReset: vi.fn(async () => 'If an account matches that email, you will receive a password reset link.'),
    updatePassword: vi.fn(async () => {}),
  })
}
beforeEach(() => { window.history.replaceState(null, '', '/'); localStorage.clear(); globalThis.fetch = vi.fn() })
afterEach(() => { setAccessTokenProvider(null); vi.restoreAllMocks(); vi.unstubAllEnvs() })

describe('accessible account actions without a live provider', () => {
  it('registers through the provider with clear confirmation messaging and clears the password immediately', async () => {
    const p = provider(); render(<HostedApp provider={p} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Create an account' }))
    const email = screen.getByLabelText('Account email'), password = screen.getByLabelText('New password')
    email.focus(); expect(document.activeElement).toBe(email)
    password.focus(); expect(document.activeElement).toBe(password)
    fireEvent.change(email, { target: { value: 'alice@example.invalid' } })
    fireEvent.change(password, { target: { value: 'offline-test-password' } })
    expect(password).toHaveAttribute('autocomplete', 'new-password')
    fireEvent.submit(password.closest('form'))
    expect(password).toHaveValue('')
    expect(await screen.findByRole('status')).toHaveTextContent('check your email')
    expect(p.register).toHaveBeenCalledWith({ email: 'alice@example.invalid', password: 'offline-test-password' })
    expect(fetch).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Back to sign-in' }))
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeEnabled()
  })
  it('requests recovery without revealing whether the account exists', async () => {
    const p = provider(); render(<HostedApp provider={p} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Forgot password?' }))
    const email = screen.getByLabelText('Account email')
    fireEvent.change(email, { target: { value: 'alice@example.invalid' } })
    fireEvent.submit(email.closest('form'))
    expect(await screen.findByRole('status')).toHaveTextContent('If an account matches')
    expect(p.requestPasswordReset).toHaveBeenCalledWith('alice@example.invalid')
    expect(screen.queryByLabelText('New password')).not.toBeInTheDocument()
  })
  it('shows a safe action error and loading state', async () => {
    const pending = deferred(), p = provider()
    p.requestPasswordReset.mockReturnValue(pending.promise)
    render(<HostedApp provider={p} />)
    fireEvent.click(await screen.findByRole('button', { name: 'Forgot password?' }))
    fireEvent.submit(screen.getByLabelText('Account email').closest('form'))
    expect(screen.getByRole('button', { name: 'Please wait…' })).toBeDisabled()
    await act(async () => pending.reject(new Error('private identity-provider diagnostics')))
    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be completed/)
    expect(document.body.textContent).not.toContain('private identity-provider diagnostics')
  })
  it('gates private views and API calls for recovery sessions, including after token rotation', async () => {
    const p = provider({ ...fakeSession(), recoveryRequired: true })
    render(<HostedApp provider={p} />)
    expect(await screen.findByRole('heading', { name: 'Reset your password' })).toBeInTheDocument()
    expect(fetch).not.toHaveBeenCalled()
    act(() => p.change({ ...fakeSession('alice', { token: 'OFFLINE-TEST-rotated' }), recoveryRequired: true }))
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
    const password = screen.getByLabelText('New password')
    fireEvent.change(password, { target: { value: 'offline-new-password' } })
    fireEvent.submit(password.closest('form'))
    expect(await screen.findByRole('status')).toHaveTextContent('Password updated')
    expect(p.updatePassword).toHaveBeenCalledWith('offline-new-password')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel and sign out' }))
    await screen.findByRole('heading', { name: 'Sign in' })
    expect(fetch).not.toHaveBeenCalled()
  })
  it('fails closed with invalid hosted configuration and does not load a real service', () => {
    vi.stubEnv('VITE_AUTH_MODE', 'hosted')
    vi.stubEnv('VITE_SUPABASE_URL', 'https://attacker.invalid')
    vi.stubEnv('VITE_SUPABASE_PUBLISHABLE_KEY', 'sb_secret_TEST_ONLY_NOT_VALID')
    render(<App />)
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeDisabled()
    expect(fetch).not.toHaveBeenCalled()
  })
})

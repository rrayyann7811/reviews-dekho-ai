import { useContext, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import FileDropzone from '../components/FileDropzone'
import PageHeader from '../components/layout/PageHeader'
import ServerNotice from '../components/ServerNotice'
import Alert from '../components/ui/Alert'
import Button from '../components/ui/Button'
import { Field, Input, Select } from '../components/ui/Field'
import Panel from '../components/ui/Panel'
import Spinner from '../components/ui/Spinner'
import { api } from '../lib/api'
import { validateReviewFile } from '../lib/files'
import { clearPendingImport, HostedUploadAccount, readPendingImport, savePendingImport } from '../lib/pendingImport'
import { plural } from '../lib/format'
import { estimatedMinutes, LARGE_ANALYSIS, largeAnalysisNotice } from '../lib/workload'
import { STATIC_DEMO } from '../lib/staticDemo'

// Columns the importer understands. Only the review text is required.
const COLUMN_ROLES = [
  { key: 'text', label: 'Review text', required: true, help: 'The written review.' },
  { key: 'rating', label: 'Star rating', help: 'A number from 1 to 5.' },
  { key: 'date', label: 'Review date', help: 'Used to sort reviews by date.' },
  { key: 'title', label: 'Review title' },
  { key: 'reviewer', label: 'Reviewer name' },
  { key: 'productName', label: 'Product name' },
  { key: 'id', label: 'Review ID', help: 'Used to skip duplicate reviews.' },
]

function FormatGuide() {
  return (
    <Panel title="File format" description="Column names don’t have to match exactly. You can choose the columns after uploading.">
      <dl className="space-y-2.5 text-[13px]">
        {COLUMN_ROLES.map((role) => (
          <div key={role.key} className="flex justify-between gap-4">
            <dt className="font-medium text-ink">{role.label}</dt>
            <dd className="text-right text-ink-3">{role.required ? 'Required' : 'Optional'}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 border-t border-line pt-4 text-[13px] text-ink-3">
        Only upload reviews you have permission to use. Rows with empty review text are skipped and reported.
      </p>
    </Panel>
  )
}

function PreviewTable({ preview }) {
  return (
    <div className="relative overflow-x-auto rounded-md border border-line">
      <table className="w-full text-left text-[13px]">
        <thead className="bg-subtle text-xs text-ink-3">
          <tr>{preview.columns.map((c) => <th key={c} scope="col" className="px-3 py-2 font-medium whitespace-nowrap">{c}</th>)}</tr>
        </thead>
        <tbody>
          {preview.sampleRows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {preview.columns.map((c) => (
                <td key={c} className="max-w-[280px] truncate px-3 py-2 text-ink-2" title={String(row[c] ?? '')}>
                  {row[c] === null || row[c] === '' ? <span className="text-ink-3">—</span> : String(row[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function UploadReviews() {
  const navigate = useNavigate()
  const owner = useContext(HostedUploadAccount)
  const [limits, setLimits] = useState(null)
  const [limitsError, setLimitsError] = useState('')
  const [pending, setPending] = useState(() => owner ? readPendingImport(owner) : null)
  const [recovery, setRecovery] = useState('')
  const inFlight = useRef(false)

  useEffect(() => {
    if (!owner || STATIC_DEMO) return
    let active = true
    api.uploadLimits().then((result) => {
      if (![result?.maxRows, result?.maxReviewChars, result?.maxUploadBytes].every(
        (value) => Number.isSafeInteger(value) && value > 0)) throw new Error('Invalid limits')
      if (active) setLimits(result)
    }).catch(() => {
      if (active) setLimitsError('Couldn’t load the upload limits. Reload this page to try again.')
    })
    return () => { active = false }
  }, [owner])

  function clearPending() {
    clearPendingImport()
    setPending(null)
    setRecovery('')
  }

  async function checkImport() {
    if (!pending || inFlight.current) return
    inFlight.current = true
    setBusy('checking')
    setRecovery('')
    try {
      const product = await api.importStatus(pending.key)
      clearPending()
      navigate(`/products/${product.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      if (err.status === 410) {
        clearPending()
        setRecovery('That import is no longer available. You can start a new import.')
      } else {
        setRecovery(err.status === 404
          ? 'No completed import is recorded yet. Check again, or select the original file and use the same import options to retry safely.'
          : 'Couldn’t check import status. Try checking again before starting another import.')
      }
    } finally {
      inFlight.current = false
      setBusy(null)
    }
  }
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState('')
  const [preview, setPreview] = useState(null)
  const [columns, setColumns] = useState({})
  const [productName, setProductName] = useState('')
  const [domain, setDomain] = useState('product')
  const [busy, setBusy] = useState(null) // 'reading' | 'importing' | null
  const [error, setError] = useState('')

  function reset() {
    setFile(null)
    setPreview(null)
    setColumns({})
    setProductName('')
    setDomain('product')
    setError('')
  }

  async function handleFile(selected) {
    reset()
    const problem = validateReviewFile(selected, limits?.maxUploadBytes)
    setFileError(problem ?? '')
    if (problem) return
    setFile(selected)
    setBusy('reading')
    try {
      const result = await api.previewUpload(selected)
      setPreview(result)
      setColumns(result.detected ?? {})
      setProductName(result.productName ?? selected.name.replace(/\.(csv|xlsx)$/i, ''))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(null)
    }
  }

  async function handleImport(event) {
    event.preventDefault()
    if (inFlight.current || (owner && !limits)) return
    if (!columns.text) return setError('Choose the column that contains the review text.')
    if (!productName.trim()) return setError('Enter a product name.')
    setError('')
    setRecovery('')
    inFlight.current = true
    setBusy('importing')
    const attempt = owner ? pending ?? savePendingImport(owner) : null
    if (attempt) setPending(attempt)
    try {
      const product = await api.importUpload(file, {
        productName: productName.trim(), columns, domain, key: attempt?.key,
      })
      if (owner) clearPending()
      navigate(`/products/${product.id}`)
    } catch (err) {
      if (err.name === 'AbortError') return
      if (attempt && (err.status == null || err.status === 408 || err.status === 499 || err.status >= 500)) {
        setRecovery('The import may have completed. Check import status before submitting again.')
      } else if (attempt && err.status === 410) {
        clearPending()
        setError(err.message)
      } else {
        if (attempt && !pending && err.status !== 409) clearPending()
        setError(err.message)
      }
    } finally {
      inFlight.current = false
      setBusy(null)
    }
  }

  return (
    <>
      <PageHeader title="Upload reviews" description="Analyse reviews from any website by uploading them as a CSV or Excel file." />
      <ServerNotice feature="Reading and analysing uploaded files" />

      <div className="grid items-start gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Panel title="1. Choose a file">
            {owner && limits && <p className="mb-3 text-sm text-ink-2">
              Up to {limits.maxRows.toLocaleString()} reviews. The first {limits.maxReviewChars.toLocaleString()} characters of each review are analysed.
            </p>}
            {limitsError && <Alert variant="error">{limitsError}</Alert>}
            {!STATIC_DEMO && pending && <Alert title="Check your previous import">
              <p>{recovery || (file ? 'This import may already have been saved.' :
                'Your previous import may have been saved. Check its status. To retry, select the original file and use the same import options.')}</p>
              <Button variant="secondary" size="sm" className="mt-2" onClick={checkImport} disabled={!!busy}>
                {busy === 'checking' ? 'Checking…' : 'Check import status'}
              </Button>
            </Alert>}
            {!pending && recovery && <Alert>{recovery}</Alert>}
            <FileDropzone file={file} onFile={handleFile} onClear={() => { reset(); setFileError('') }} error={fileError} maxBytes={limits?.maxUploadBytes} disabled={!!busy || STATIC_DEMO || Boolean(owner && !limits)} />
            {busy === 'reading' && <Spinner className="mt-4" label="Reading file…" />}
            {error && !preview && <Alert variant="error" title="Couldn’t read this file" className="mt-4">{error}</Alert>}
          </Panel>

          {preview && (
            <Panel
              title="2. Check the data"
              description={`${plural(preview.rowCount, 'row')} found. Showing the first ${preview.sampleRows.length}.`}
            >
              <form onSubmit={handleImport} className="space-y-5">
                <PreviewTable preview={preview} />
                {preview.warnings?.map((w) => <Alert key={w} variant="warning">{w}</Alert>)}
                {largeAnalysisNotice(preview.rowCount) && <Alert title="Large file">{largeAnalysisNotice(preview.rowCount)}</Alert>}

                <div>
                  <h3 className="mb-3 text-[13px] font-semibold">Match your columns</h3>
                  <div className="grid gap-4 sm:grid-cols-2">
                    {COLUMN_ROLES.map((role) => (
                      <Field key={role.key} label={`${role.label}${role.required ? '' : ' (optional)'}`} hint={role.help}>
                        {(props) => (
                          <Select {...props} value={columns[role.key] ?? ''} onChange={(e) => setColumns({ ...columns, [role.key]: e.target.value || null })}>
                            <option value="">{role.required ? 'Choose a column…' : 'Not in this file'}</option>
                            {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                          </Select>
                        )}
                      </Field>
                    ))}
                  </div>
                </div>

                <div className="grid gap-4 sm:grid-cols-2">
                  <Field label="Product name" hint="Shown in your history and reports.">
                    {(props) => <Input {...props} value={productName} onChange={(e) => setProductName(e.target.value)} />}
                  </Field>
                  <Field label="What do these reviews describe?" hint="Chooses which features are looked for.">
                    {(props) => (
                      <Select {...props} value={domain} onChange={(e) => setDomain(e.target.value)}>
                        <option value="product">A physical product (battery, delivery, price…)</option>
                        <option value="app">A mobile app (login, crashes, ads…)</option>
                      </Select>
                    )}
                  </Field>
                </div>

                {error && <Alert variant="error">{error}</Alert>}
                {busy === 'importing' && (
                  <Spinner label={preview.rowCount > LARGE_ANALYSIS
                    ? `Importing and analysing ${plural(preview.rowCount, 'row')}… this can take about ${estimatedMinutes(preview.rowCount)} minutes. Keep this page open.`
                    : owner ? 'Importing and analysing the reviews… Keep this page open.' : 'Importing and analysing the reviews…'} />
                )}
                <div className="flex justify-end gap-2 border-t border-line pt-4">
                  <Button variant="secondary" onClick={() => { reset(); setFileError('') }} disabled={!!busy}>Cancel</Button>
                  <Button type="submit" disabled={!!busy}>{busy === 'importing' ? 'Analysing…' : pending ? 'Retry same import' : 'Import and analyse'}</Button>
                </div>
              </form>
            </Panel>
          )}
        </div>
        <FormatGuide />
      </div>
    </>
  )
}

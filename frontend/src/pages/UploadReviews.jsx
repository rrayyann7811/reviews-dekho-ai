import { useState } from 'react'
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
    const problem = validateReviewFile(selected)
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
    if (!columns.text) return setError('Choose the column that contains the review text.')
    if (!productName.trim()) return setError('Enter a product name.')
    setError('')
    setBusy('importing')
    try {
      const product = await api.importUpload(file, { productName: productName.trim(), columns, domain })
      navigate(`/products/${product.id}`)
    } catch (err) {
      setError(err.message)
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
            <FileDropzone file={file} onFile={handleFile} onClear={() => { reset(); setFileError('') }} error={fileError} disabled={!!busy || STATIC_DEMO} />
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
                    : 'Importing and analysing the reviews…'} />
                )}
                <div className="flex justify-end gap-2 border-t border-line pt-4">
                  <Button variant="secondary" onClick={() => { reset(); setFileError('') }} disabled={!!busy}>Cancel</Button>
                  <Button type="submit" disabled={!!busy}>{busy === 'importing' ? 'Analysing…' : 'Import and analyse'}</Button>
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

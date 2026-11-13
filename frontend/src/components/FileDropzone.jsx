import { FileSpreadsheet, Upload, X } from 'lucide-react'
import { useRef, useState } from 'react'
import { MAX_FILE_BYTES, ACCEPTED_EXTENSIONS } from '../lib/files'
import { formatFileSize } from '../lib/format'

export default function FileDropzone({ file, onFile, onClear, error, disabled }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)

  function pick(files) {
    if (files?.length) onFile(files[0])
  }

  if (file) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-line bg-subtle px-4 py-3">
        <FileSpreadsheet aria-hidden className="size-5 shrink-0 text-brand-600" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-ink">{file.name}</p>
          <p className="text-xs text-ink-3">{formatFileSize(file.size)}</p>
        </div>
        <button type="button" onClick={onClear} disabled={disabled}
          className="flex size-8 items-center justify-center rounded-md text-ink-3 hover:bg-black/[0.05] hover:text-ink disabled:opacity-50"
          aria-label="Remove file">
          <X className="size-4" />
        </button>
      </div>
    )
  }

  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); pick(e.dataTransfer.files) }}
        className={`flex flex-col items-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? 'border-brand-600 bg-brand-50' : error ? 'border-neg/50 bg-surface' : 'border-line-strong bg-surface'
        }`}
      >
        <Upload aria-hidden className="mb-3 size-5 text-ink-3" />
        <p className="text-sm text-ink">
          Drag a file here, or{' '}
          <button type="button" onClick={() => inputRef.current?.click()} className="font-medium text-brand-600 hover:underline">
            choose a file
          </button>
        </p>
        <p className="mt-1 text-[13px] text-ink-3">CSV or Excel (.xlsx), up to {formatFileSize(MAX_FILE_BYTES)}</p>
        <input ref={inputRef} type="file" accept={ACCEPTED_EXTENSIONS.join(',')} className="sr-only" tabIndex={-1}
          aria-label="Review file" onChange={(e) => { pick(e.target.files); e.target.value = '' }} />
      </div>
      {error && <p role="alert" className="mt-2 text-[13px] text-neg">{error}</p>}
    </div>
  )
}

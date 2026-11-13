const dateFormat = new Intl.DateTimeFormat('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })

export function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date)
}

export function formatPercent(value) {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toFixed(1).replace(/\.0$/, '')}%`
}

export function formatRating(value) {
  return value === null || value === undefined ? '—' : Number(value).toFixed(1)
}

export function plural(count, singular, pluralForm = `${singular}s`) {
  return `${count.toLocaleString('en-IN')} ${count === 1 ? singular : pluralForm}`
}

export function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

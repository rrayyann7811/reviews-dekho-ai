import { formatFileSize } from './format'

export const MAX_FILE_BYTES = 10 * 1024 * 1024
export const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx']

/** Returns an error message, or null when the file is acceptable. */
export function validateReviewFile(file) {
  const name = file.name.toLowerCase()
  if (!ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `“${file.name}” isn’t a CSV or Excel (.xlsx) file. Older .xls files need to be re-saved as .xlsx.`
  }
  if (file.size === 0) return `“${file.name}” is empty.`
  if (file.size > MAX_FILE_BYTES) {
    return `“${file.name}” is ${formatFileSize(file.size)}. The limit is ${formatFileSize(MAX_FILE_BYTES)}.`
  }
  return null
}

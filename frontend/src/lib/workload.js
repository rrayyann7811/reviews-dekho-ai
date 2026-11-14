// Expected analysis time for large inputs, from the Phase 8 measurement: the pretrained model read about 190 texts per
// second on an Apple M3 with 8 GB RAM, and each review is about two texts (the review, plus its feature phrases).
export const LARGE_ANALYSIS = 5000
const TEXTS_PER_REVIEW = 2
const TEXTS_PER_SECOND = 190

/** A rough "about N minutes" for analysing `count` reviews with the pretrained model (VADER is much faster). */
export function estimatedMinutes(count) {
  return Math.max(1, Math.round((count * TEXTS_PER_REVIEW) / TEXTS_PER_SECOND / 60))
}

/** Advice for inputs above LARGE_ANALYSIS reviews, or null for smaller ones. */
export function largeAnalysisNotice(count) {
  if (!count || count <= LARGE_ANALYSIS) return null
  const minutes = estimatedMinutes(count)
  return `Analysing ${count.toLocaleString('en-IN')} reviews takes a while: about ${minutes} ${minutes === 1 ? 'minute' : 'minutes'} `
    + 'with the pretrained sentiment model on a typical laptop (measured on an Apple M3 with 8 GB RAM; slower computers take '
    + 'longer, and VADER is much faster). Keep this page open until it finishes.'
}

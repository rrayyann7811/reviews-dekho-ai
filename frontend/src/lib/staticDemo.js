// The static, demo-only build (`npm run build:demo`, Vite mode "staticdemo"): no backend is contacted at all — not
// even the visitor's own localhost — and only the built-in demo product (synthetic reviews) is shown.
export const STATIC_DEMO = import.meta.env.MODE === 'staticdemo'

export const STATIC_DEMO_MESSAGE =
  'This online demo shows the interface with the built-in demo product, whose reviews are synthetic. Uploading files, ' +
  'collecting App Store reviews, history, comparisons and reports need the full app running on your own computer — ' +
  'see the README.'

// Short texts for the places where the static demo replaces a local-app feature.
export const STATIC_DEMO_TEXT = {
  status: 'Online demo',
  collect: 'Collecting reviews from links needs the full app running on your own computer. In this online demo you can open the built-in demo product instead.',
  history: 'This online demo has no saved analyses, so only the built-in demo product is listed. Real analysis history is kept by the full app running on your own computer — see the README.',
  compare: 'Comparisons use saved analysis runs, which the full app keeps on your own computer. The built-in demo product can’t be compared.',
  unavailable: 'Not available in the online demo — it needs the full app running on your own computer.',
}

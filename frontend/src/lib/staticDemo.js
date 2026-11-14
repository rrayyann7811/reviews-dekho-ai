// The static, demo-only build (`npm run build:demo`, Vite mode "staticdemo"): no backend is contacted at all — not
// even the visitor's own localhost — and only the built-in demo product (synthetic reviews) is shown.
export const STATIC_DEMO = import.meta.env.MODE === 'staticdemo'

export const STATIC_DEMO_MESSAGE =
  'This is the online demo, which shows only the built-in demo product (synthetic reviews). Uploading files, collecting ' +
  'App Store reviews, history, comparisons and reports need the app running on your own computer — see the README.'

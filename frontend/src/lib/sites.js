// Websites the URL analyser recognises. "supported" means reviews can be
// retrieved through a permitted source; "unavailable" means we recognise the
// link but the site offers no permitted way to collect its reviews.
// Mirrors backend/app/collectors (GET /api/sites); a backend test keeps them in sync.
export const SITES = [
  {
    id: 'demo',
    name: 'Demo store',
    hosts: ['demo.reviewsdekho.test'],
    status: 'supported',
    note: 'Sample products with synthetic reviews, for trying every feature.',
    example: 'https://demo.reviewsdekho.test/product/kestrel-orbit-5g',
  },
  {
    id: 'apple_app_store',
    name: 'Apple App Store',
    hosts: ['apps.apple.com', 'itunes.apple.com'],
    status: 'supported',
    note: 'Apps on the App Store. Up to the 500 most recent written reviews from the country store in the link, through Apple’s public review feed.',
    example: 'https://apps.apple.com/in/app/whatsapp-messenger/id310633997',
  },
  {
    id: 'amazon',
    name: 'Amazon',
    hosts: ['amazon.in', 'amazon.com', 'amazon.co.uk', 'amzn.in', 'amzn.to', 'amzn.eu'],
    status: 'unavailable',
    note: 'Link recognised. Amazon does not provide public access to reviews, so they cannot be collected automatically.',
  },
  {
    id: 'flipkart',
    name: 'Flipkart',
    hosts: ['flipkart.com', 'dl.flipkart.com'],
    status: 'unavailable',
    note: 'Link recognised. Flipkart does not provide public access to reviews, so they cannot be collected automatically.',
  },
]

// The only demo product link that resolves to data in this version.
export const DEMO_PRODUCT_PATH = '/product/kestrel-orbit-5g'

/** Validate user input and return { url } or { error }. */
export function parseProductUrl(input) {
  const raw = input.trim()
  if (!raw) return { error: 'Enter a product link.' }
  const withScheme = /^https?:\/\//i.test(raw) ? raw : `https://${raw}`
  let url
  try {
    url = new URL(withScheme)
  } catch {
    return { error: 'This doesn’t look like a web address. Copy the link from your browser’s address bar.' }
  }
  if (!['http:', 'https:'].includes(url.protocol) || !url.hostname.includes('.')) {
    return { error: 'This doesn’t look like a web address. Copy the link from your browser’s address bar.' }
  }
  return { url }
}

export function detectSite(url) {
  const host = url.hostname.toLowerCase().replace(/^www\./, '')
  return SITES.find((site) => site.hosts.some((h) => host === h || host.endsWith(`.${h}`))) ?? null
}

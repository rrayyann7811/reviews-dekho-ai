import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from '../App'
import demo from '../demo/demoAnalysis.json'
import { ServerStatusProvider } from '../lib/serverStatus'
import { SettingsProvider } from '../lib/settings'

function renderAt(path) {
  return render(
    <SettingsProvider>
      <ServerStatusProvider>
        <MemoryRouter initialEntries={[path]}>
          <AppRoutes />
        </MemoryRouter>
      </ServerStatusProvider>
    </SettingsProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  // Simulate the backend being offline: the app must still work with demo data.
  globalThis.fetch = vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
})

describe('navigation', () => {
  const pages = [
    ['/', 'Overview'],
    ['/analyze', 'Analyze a product link'],
    ['/upload', 'Upload reviews'],
    ['/history', 'Analysis history'],
    ['/compare', 'Compare products'],
    ['/reports', 'Reports'],
    ['/settings', 'Settings'],
    ['/nowhere', 'Page not found'],
  ]
  it.each(pages)('%s renders its page', async (path, heading) => {
    renderAt(path)
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()   // every page has one h1
  })

  it('sidebar links move between pages', async () => {
    renderAt('/')
    const nav = screen.getAllByRole('navigation', { name: 'Main' })[0]
    fireEvent.click(within(nav).getByRole('link', { name: 'Upload reviews' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Upload reviews' })).toBeInTheDocument()
    fireEvent.click(within(nav).getByRole('link', { name: 'Analysis history' }))
    expect(await screen.findByRole('heading', { level: 1, name: 'Analysis history' })).toBeInTheDocument()
  })

  it('shows the server as offline', async () => {
    renderAt('/')
    expect(await screen.findByText('Server offline')).toBeInTheDocument()
  })
})

describe('product link form', () => {
  const submit = (value) => {
    fireEvent.change(screen.getByLabelText('Product link'), { target: { value } })
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
  }

  it('shows a validation error for invalid input', async () => {
    renderAt('/analyze')
    submit('hello world')
    expect(await screen.findByText(/doesn’t look like a web address/)).toBeInTheDocument()
  })
  it('explains that Amazon reviews cannot be collected and offers alternatives', async () => {
    renderAt('/analyze')
    submit('https://www.amazon.in/dp/B0ABCDEFGH')
    expect(await screen.findByText('Amazon reviews can’t be collected automatically')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Upload a review file' })).toHaveAttribute('href', '/upload')
  })
  it('reports unsupported websites', async () => {
    renderAt('/analyze')
    await screen.findByText('Server offline')
    submit('https://shop.example.com/item/42')
    expect(await screen.findByText('shop.example.com isn’t supported yet')).toBeInTheDocument()
  })
  it('opens the demo product from its link', async () => {
    renderAt('/analyze')
    fireEvent.click(screen.getByRole('button', { name: 'Use the demo product link' }))
    fireEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    expect(await screen.findByRole('heading', { level: 1, name: demo.product.name })).toBeInTheDocument()
  })
})

describe('upload page', () => {
  it('rejects an unsupported file type without contacting the server', async () => {
    renderAt('/upload')
    const input = screen.getByLabelText('Review file')
    fireEvent.change(input, { target: { files: [new File(['x'], 'notes.pdf', { type: 'application/pdf' })] } })
    expect(await screen.findByText(/isn’t a CSV or Excel/)).toBeInTheDocument()
  })
  it('shows a clear error when the server cannot read the file', async () => {
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['a,b\n1,2'], 'reviews.csv', { type: 'text/csv' })] } })
    expect(await screen.findByText('Couldn’t read this file')).toBeInTheDocument()
    expect(screen.getByText(/Can’t reach the analysis server/)).toBeInTheDocument()
  })
  it('previews a file and lets the user map columns', async () => {
    globalThis.fetch = vi.fn((url) => {
      if (url.endsWith('/health')) return Promise.resolve(new Response('{}', { headers: { 'content-type': 'application/json' } }))
      if (url.endsWith('/products')) return Promise.resolve(new Response('[]', { headers: { 'content-type': 'application/json' } }))
      return Promise.resolve(new Response(JSON.stringify({
        rowCount: 2, columns: ['Comment', 'Stars'], sampleRows: [{ Comment: 'Great', Stars: 5 }, { Comment: 'Bad', Stars: 1 }],
        detected: { text: 'Comment', rating: 'Stars' }, productName: 'My product',
      }), { headers: { 'content-type': 'application/json' } }))
    })
    renderAt('/upload')
    fireEvent.change(screen.getByLabelText('Review file'), { target: { files: [new File(['Comment,Stars'], 'r.csv', { type: 'text/csv' })] } })
    expect(await screen.findByText('2 rows found. Showing the first 2.')).toBeInTheDocument()
    expect(screen.getByLabelText('Review text')).toHaveValue('Comment')
    expect(screen.getByLabelText('Star rating (optional)')).toHaveValue('Stars')
  })
})

describe('product analysis (demo)', () => {
  it('shows the demo label and figures computed from the data', async () => {
    renderAt('/products/demo')
    expect(await screen.findByText('Demo data', { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByText('Reviews analysed').nextSibling).toHaveTextContent(String(demo.stats.totalReviews))
  })
  it('review explorer filters change the visible reviews', async () => {
    renderAt('/products/demo?tab=reviews')
    const total = demo.stats.totalReviews
    expect(await screen.findByText(`Showing 20 of ${total} matching reviews (${total} total)`)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Filter by sentiment'), { target: { value: 'negative' } })
    const neg = demo.stats.sentimentCounts.negative
    expect(screen.getByText(`Showing ${Math.min(20, neg)} of ${neg} matching reviews (${total} total)`)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Search reviews'), { target: { value: 'zzzz-no-match' } })
    expect(screen.getByText('No reviews match these filters')).toBeInTheDocument()
  })
  it('switches to the features tab', async () => {
    renderAt('/products/demo')
    fireEvent.click(await screen.findByRole('tab', { name: 'Features & keywords' }))
    expect(screen.getByRole('table')).toHaveTextContent('Battery')
  })
})

describe('settings page', () => {
  it('describes the current method: RoBERTa by default, VADER as the fallback, English only', async () => {
    renderAt('/settings')
    const method = (await screen.findByRole('heading', { name: 'How the analysis works' })).closest('section')
    expect(method).toHaveTextContent('pretrained language model (Twitter-RoBERTa by Cardiff NLP)')
    expect(method).toHaveTextContent('the whole run uses VADER instead')
    expect(method).toHaveTextContent('Only English is analysed')
    expect(method).toHaveTextContent('left out of the sentiment and feature figures')
    expect(method).not.toHaveTextContent('Each review is scored with VADER')
  })
})

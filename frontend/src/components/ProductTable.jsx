import { useNavigate } from 'react-router-dom'
import { formatDate, formatPercent, formatRating } from '../lib/format'
import { SourceBadge } from './ui/Badge'

/** Table of analysed products. Each row opens that product's analysis. */
export default function ProductTable({ products }) {
  const navigate = useNavigate()
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="bg-subtle text-xs text-ink-3">
          <tr>
            <th scope="col" className="px-5 py-2.5 font-medium">Product</th>
            <th scope="col" className="px-3 py-2.5 font-medium">Source</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Reviews</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Avg. rating</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Positive</th>
            <th scope="col" className="px-5 py-2.5 text-right font-medium">Analysed</th>
          </tr>
        </thead>
        <tbody>
          {products.map((p) => (
            <tr
              key={p.id}
              onClick={() => navigate(`/products/${p.id}`)}
              className="cursor-pointer border-t border-line transition-colors hover:bg-subtle"
            >
              <td className="px-5 py-3">
                {/* A real link keeps keyboard and middle-click navigation working. */}
                <a href={`/products/${p.id}`} onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/products/${p.id}`) }}
                  className="font-medium text-ink hover:text-brand-700">
                  {p.name}
                </a>
                {p.category && <div className="text-xs text-ink-3">{p.category}</div>}
              </td>
              <td className="px-3 py-3"><SourceBadge source={p.source} /></td>
              <td className="px-3 py-3 text-right tabular-nums">{p.totalReviews}</td>
              <td className="px-3 py-3 text-right tabular-nums">{formatRating(p.averageRating)}</td>
              <td className="px-3 py-3 text-right tabular-nums">{formatPercent(p.positivePercent)}</td>
              <td className="px-5 py-3 text-right whitespace-nowrap text-ink-2">{formatDate(p.analyzedAt)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

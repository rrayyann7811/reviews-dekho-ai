import { Fragment, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import SplitBar from '../charts/SplitBar'
import { SentimentBadge } from '../ui/Badge'

function Example({ label, example, onOpenReview }) {
  if (!example) return null
  return (
    <p className="text-[13px] text-ink-2">
      <span className="text-ink-3">{label}: </span>“{example.text}”{' '}
      <button type="button" onClick={() => onOpenReview(example.reviewId)} className="text-xs text-brand-600 hover:underline">Read review</button>
    </p>
  )
}

export default function AspectTable({ aspects, onOpenReview }) {
  const [open, setOpen] = useState(null)
  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[620px] text-left text-sm">
        <thead className="bg-subtle text-xs text-ink-3">
          <tr>
            <th scope="col" className="px-5 py-2.5 font-medium">Feature</th>
            <th scope="col" className="px-3 py-2.5 text-right font-medium">Mentions</th>
            <th scope="col" className="w-[34%] px-3 py-2.5 font-medium">Positive / neutral / negative</th>
            <th scope="col" className="px-3 py-2.5 font-medium">Overall</th>
            <th scope="col" className="px-5 py-2.5"><span className="sr-only">Examples</span></th>
          </tr>
        </thead>
        <tbody>
          {aspects.map((row) => (
            <Fragment key={row.aspect}>
              <tr className="border-t border-line">
                <td className="px-5 py-3 font-medium">{row.aspect}</td>
                <td className="px-3 py-3 text-right tabular-nums">{row.mentions}</td>
                <td className="px-3 py-3">
                  <div className="flex items-center gap-3">
                    <SplitBar positive={row.positive} neutral={row.neutral} negative={row.negative} total={row.mentions}
                      label={`${row.aspect}: ${row.positive} positive, ${row.neutral} neutral, ${row.negative} negative mentions`} />
                    <span className="text-xs whitespace-nowrap text-ink-3 tabular-nums">{row.positive} / {row.neutral} / {row.negative}</span>
                  </div>
                </td>
                <td className="px-3 py-3"><SentimentBadge value={row.verdict} /></td>
                <td className="px-5 py-3 text-right">
                  <button type="button" onClick={() => setOpen(open === row.aspect ? null : row.aspect)} aria-expanded={open === row.aspect}
                    className="inline-flex items-center gap-1 text-[13px] text-brand-600 hover:underline">
                    Examples <ChevronDown aria-hidden className={`size-3.5 transition-transform ${open === row.aspect ? 'rotate-180' : ''}`} />
                  </button>
                </td>
              </tr>
              {open === row.aspect && (
                <tr className="bg-subtle">
                  <td colSpan={5} className="space-y-1.5 px-5 py-3">
                    <Example label="Most positive" example={row.examplePositive} onOpenReview={onOpenReview} />
                    <Example label="Most negative" example={row.exampleNegative} onOpenReview={onOpenReview} />
                    {!row.examplePositive && !row.exampleNegative && <p className="text-[13px] text-ink-3">All mentions are neutral.</p>}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  )
}

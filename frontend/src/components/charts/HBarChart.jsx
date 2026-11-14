import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { colors } from '../../lib/theme'

function ChartTooltip({ active, payload, describe }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-md border border-line bg-surface px-3 py-2 text-xs shadow-sm">
      <p className="font-medium text-ink">{row.label}</p>
      <p className="mt-0.5 text-ink-2">{describe(row)}</p>
    </div>
  )
}

/**
 * Horizontal bar chart for one measure across a few categories.
 * data: [{ label, value, color? }]. Bars use the brand colour unless a row sets its own.
 *
 * The value text ("126 · 25.7%") is drawn as a second category axis on the right, so every row,
 * including zero rows, is labelled by its own category. (Recharts' bar labels skip zero-length bars,
 * which shifted later labels onto the wrong rows.)
 */
export default function HBarChart({ data, valueLabel, describe, labelWidth = 84, rowHeight = 34, ariaLabel }) {
  const max = Math.max(...data.map((d) => d.value), 1)
  const rows = data.map((d, i) => ({ ...d, valueText: valueLabel(d), key: i }))
  return (
    <div role="img" aria-label={ariaLabel} style={{ height: data.length * rowHeight + 8 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 0, bottom: 4, left: 0 }} barCategoryGap={8}>
          <XAxis type="number" hide domain={[0, max]} />
          <YAxis type="category" dataKey="label" width={labelWidth} axisLine={false} tickLine={false}
            tick={{ fill: colors.axis, fontSize: 13 }} />
          <YAxis yAxisId="values" orientation="right" type="category" dataKey="valueText" width={96} axisLine={false}
            tickLine={false} allowDuplicatedCategory tick={{ fill: '#4b4e54', fontSize: 13 }} />
          <Tooltip cursor={{ fill: 'rgba(0,0,0,0.03)' }} content={<ChartTooltip describe={describe} />} isAnimationActive={false} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}
            background={{ fill: '#f3f3f1', radius: 4 }}>
            {rows.map((d) => <Cell key={d.key} fill={d.color ?? colors.brand} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

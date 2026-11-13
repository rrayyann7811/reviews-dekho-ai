import { Bar, BarChart, Cell, LabelList, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
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
 */
export default function HBarChart({ data, valueLabel, describe, labelWidth = 84, rowHeight = 34, ariaLabel }) {
  const max = Math.max(...data.map((d) => d.value), 1)
  return (
    <div role="img" aria-label={ariaLabel} style={{ height: data.length * rowHeight + 8 }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 4, right: 88, bottom: 4, left: 0 }} barCategoryGap={8}>
          <XAxis type="number" hide domain={[0, max]} />
          <YAxis type="category" dataKey="label" width={labelWidth} axisLine={false} tickLine={false}
            tick={{ fill: colors.axis, fontSize: 13 }} />
          <Tooltip cursor={{ fill: 'rgba(0,0,0,0.03)' }} content={<ChartTooltip describe={describe} />} isAnimationActive={false} />
          <Bar dataKey="value" radius={[0, 4, 4, 0]} maxBarSize={18} isAnimationActive={false}
            background={{ fill: '#f3f3f1', radius: 4 }}>
            {data.map((d) => <Cell key={d.label} fill={d.color ?? colors.brand} />)}
            <LabelList dataKey="value" position="right" content={({ x, y, width, height, index }) => (
              <text x={x + width + 8} y={y + height / 2} dominantBaseline="central" fontSize={13} fill="#4b4e54">
                {valueLabel(data[index])}
              </text>
            )} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

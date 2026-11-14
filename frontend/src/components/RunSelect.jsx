import { formatDate } from '../lib/format'
import { Field, Select } from './ui/Field'

/** Run picker. The value '' means "the latest run", so a newer run is picked up automatically. */
export default function RunSelect({ runs, value, onChange, label = 'Analysis run', hint }) {
  return (
    <Field label={label} hint={hint}>
      {(props) => (
        <Select {...props} value={value} onChange={(e) => onChange(e.target.value)}>
          {runs.map((run, i) => (
            <option key={run.id} value={i === 0 ? '' : run.id}>
              {i === 0 ? 'Latest' : 'Run'} #{run.id} · {formatDate(run.createdAt)} · {run.totalReviews} reviews
            </option>
          ))}
        </Select>
      )}
    </Field>
  )
}

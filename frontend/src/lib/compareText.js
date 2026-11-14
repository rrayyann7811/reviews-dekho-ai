// Wording shared by the comparison page's components.
import { formatPercent } from './format'

export function intervalText(interval) {
  return interval ? `95% interval ${formatPercent(interval[0])}–${formatPercent(interval[1])}` : ''
}

/** "A is 12.5 points higher than B" — plain arithmetic, no judgement. */
export function differenceText(difference, unit = 'points') {
  if (difference == null) return null
  if (difference === 0) return 'Same share on both sides'
  return `A is ${Math.abs(difference).toLocaleString('en-IN')} ${unit} ${difference > 0 ? 'higher' : 'lower'} than B`
}

export const FEATURE_STATUS = {
  compared: 'Compared',
  'few-mentions': 'Too few mentions to compare',
  'not-mentioned': 'Looked for, not mentioned',
  'not-looked-for': 'Not looked for',
  unknown: 'Unknown (older run)',
}

export const FEATURE_STATUS_HELP = {
  'few-mentions': 'Fewer than 3 mentions: shown, but not compared.',
  'not-mentioned': 'Looked for, and no analysed review mentioned it.',
  'not-looked-for': 'That run used a different feature list, so the feature wasn’t looked for. This is missing information, not a zero.',
  unknown: 'That older run didn’t record which features it looked for.',
}

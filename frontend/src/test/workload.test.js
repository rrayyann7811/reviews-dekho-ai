import { describe, expect, it } from 'vitest'
import { estimatedMinutes, LARGE_ANALYSIS, largeAnalysisNotice } from '../lib/workload'

describe('large-analysis estimate', () => {
  it('uses the measured rate: about two texts per review at 190 texts per second', () => {
    expect(LARGE_ANALYSIS).toBe(5000)
    expect(estimatedMinutes(20000)).toBe(4)     // 40,000 texts / 190 per second ≈ 3.5 minutes
    expect(estimatedMinutes(6000)).toBe(1)
    expect(estimatedMinutes(10)).toBe(1)         // never "0 minutes"
  })
  it('only warns above 5,000 reviews', () => {
    expect(largeAnalysisNotice(5000)).toBeNull()
    expect(largeAnalysisNotice(undefined)).toBeNull()
    expect(largeAnalysisNotice(5001)).toMatch(/^Analysing 5,001 reviews takes a while: about 1 minute with/)
  })
})

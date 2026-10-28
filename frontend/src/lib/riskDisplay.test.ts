import { describe, expect, it } from 'vitest'

import { riskColorVar, riskLabel } from '@/lib/riskDisplay'
import { RISK_LEVELS, type RiskLevel } from '@/types/risk'

describe('risk display helpers', () => {
  it('labels every risk level the backend can return', () => {
    for (const level of RISK_LEVELS) {
      expect(riskLabel(level)).toBeTruthy()
    }
  })

  it.each<[RiskLevel, string]>([
    ['LOW', 'Low'],
    ['MODERATE', 'Moderate'],
    ['HIGH', 'High'],
    ['SEVERE', 'Severe'],
    ['NO_TRAVEL', 'No Travel'],
    ['UNKNOWN', 'Unknown'],
  ])('renders %s as "%s"', (level, expected) => {
    expect(riskLabel(level)).toBe(expected)
  })

  it('maps each level to a distinct CSS custom property', () => {
    const vars = RISK_LEVELS.map(riskColorVar)
    expect(new Set(vars).size).toBe(RISK_LEVELS.length)
    expect(riskColorVar('NO_TRAVEL')).toBe('var(--risk-no-travel)')
  })

  it('orders levels from least to most severe', () => {
    expect(RISK_LEVELS.indexOf('LOW')).toBeLessThan(RISK_LEVELS.indexOf('SEVERE'))
    expect(RISK_LEVELS.indexOf('SEVERE')).toBeLessThan(
      RISK_LEVELS.indexOf('NO_TRAVEL'),
    )
  })
})

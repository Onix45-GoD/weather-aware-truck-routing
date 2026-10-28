import type { RiskLevel } from '@/types/risk'

/** Human-readable label for a risk level. */
export function riskLabel(level: RiskLevel): string {
  return RISK_LABELS[level]
}

/** CSS custom-property name carrying this level's colour. */
export function riskColorVar(level: RiskLevel): string {
  return `var(--risk-${level.toLowerCase().replace('_', '-')})`
}

const RISK_LABELS: Record<RiskLevel, string> = {
  LOW: 'Low',
  MODERATE: 'Moderate',
  HIGH: 'High',
  SEVERE: 'Severe',
  NO_TRAVEL: 'No Travel',
  UNKNOWN: 'Unknown',
}

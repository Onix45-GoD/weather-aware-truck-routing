/**
 * Visual treatment for each backend risk level.
 *
 * **This file maps enums to colours and labels. It contains no thresholds.**
 * Which level a checkpoint has is decided entirely by the Django domain
 * engine; the frontend only renders the answer. Reimplementing a threshold
 * here would create a second copy that silently drifts from the real one.
 */

import type { RiskLevel } from '@/api/types'

export interface RiskStyle {
  /** Short label for chips and legends. */
  label: string
  /** Longer label for prose and screen readers. */
  description: string
  color: string
  /** Translucent fill for map overlays and backgrounds. */
  soft: string
  /** Text colour that meets contrast on `color`. */
  contrastText: string
}

export const RISK_STYLES: Record<RiskLevel, RiskStyle> = {
  LOW: {
    label: 'Low',
    description: 'Low risk',
    color: '#22C55E',
    soft: 'rgba(34, 197, 94, 0.16)',
    contrastText: '#06240F',
  },
  MODERATE: {
    label: 'Moderate',
    description: 'Moderate risk',
    color: '#F59E0B',
    soft: 'rgba(245, 158, 11, 0.16)',
    contrastText: '#2A1A00',
  },
  HIGH: {
    label: 'High',
    description: 'High risk',
    color: '#F97316',
    soft: 'rgba(249, 115, 22, 0.16)',
    contrastText: '#2A1000',
  },
  SEVERE: {
    label: 'Severe',
    description: 'Severe risk',
    color: '#EF4444',
    soft: 'rgba(239, 68, 68, 0.18)',
    contrastText: '#2B0606',
  },
  NO_TRAVEL: {
    label: 'No Travel',
    description: 'No travel — conditions make this stretch unsafe',
    color: '#A855F7',
    soft: 'rgba(168, 85, 247, 0.18)',
    contrastText: '#1B0430',
  },
  UNKNOWN: {
    /**
     * Deliberately not styled like Low. A forecast gap is an absence of
     * information, not an all-clear, and must never read as one.
     */
    label: 'No data',
    description: 'No forecast available for this point',
    color: '#64748B',
    soft: 'rgba(100, 116, 139, 0.18)',
    contrastText: '#0B1220',
  },
}

/** Severity order for legends and sorting. `UNKNOWN` sits outside it. */
export const RISK_ORDER: readonly RiskLevel[] = [
  'LOW',
  'MODERATE',
  'HIGH',
  'SEVERE',
  'NO_TRAVEL',
]

export function riskStyle(level: RiskLevel): RiskStyle {
  return RISK_STYLES[level] ?? RISK_STYLES.UNKNOWN
}

export function riskLabel(level: RiskLevel): string {
  return riskStyle(level).label
}

export function riskColor(level: RiskLevel): string {
  return riskStyle(level).color
}

/**
 * MapLibre `match` expression pairs for colouring features by risk level.
 * Flat `[value, output, value, output, ...]`, as the expression spec wants.
 */
export function riskMatchExpression(): Array<string> {
  return Object.entries(RISK_STYLES).flatMap(([level, style]) => [
    level,
    style.color,
  ])
}

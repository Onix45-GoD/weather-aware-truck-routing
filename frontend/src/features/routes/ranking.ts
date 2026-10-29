import type {
  AnalysedRoute,
  Checkpoint,
  RiskLevel,
  RouteAnalysisResponse,
  RouteMetrics,
} from '@/api/types'
import { averageRisk, duration, miles } from '@/lib/format'

/**
 * Presentation helpers for the ranking the backend already decided.
 *
 * **Nothing here ranks.** Every sentence is derived from
 * `separated_from_previous_by` -- the criterion the domain engine recorded
 * when it placed one route below another -- and the two routes' metrics.
 * This file turns that record into words and highlights; it never compares
 * Severe miles itself to decide who is better.
 */

/** The sort-key positions the backend reports, in its order. */
export type Criterion =
  | 'eligibility'
  | 'severe_miles'
  | 'high_miles'
  | 'average_risk'
  | 'duration_seconds'
  | 'unknown_miles'
  | 'provider_order'
  | 'route_id'

/** The columns of the comparison table, in display order. */
export type ComparisonColumn =
  | 'severe'
  | 'high'
  | 'average'
  | 'duration'
  | 'coverage'
  | 'status'

/** Which table column a deciding criterion lands in. */
export function criterionColumn(criterion: string | null): ComparisonColumn | null {
  switch (criterion) {
    case 'severe_miles':
      return 'severe'
    case 'high_miles':
      return 'high'
    case 'average_risk':
      return 'average'
    case 'duration_seconds':
      return 'duration'
    case 'unknown_miles':
      return 'coverage'
    case 'eligibility':
      return 'status'
    default:
      return null
  }
}

/** Short label for the criterion that separated a route from the one above. */
export function criterionLabel(criterion: string | null): string {
  switch (criterion) {
    case 'severe_miles':
      return 'Severe miles'
    case 'high_miles':
      return 'High miles'
    case 'average_risk':
      return 'average risk'
    case 'duration_seconds':
      return 'drive time'
    case 'unknown_miles':
      return 'unforecast miles'
    case 'eligibility':
      return 'eligibility'
    case 'provider_order':
    case 'route_id':
      return 'provider order (all criteria tie)'
    default:
      return ''
  }
}

function ordinal(rank: number): string {
  const suffix =
    rank % 100 >= 11 && rank % 100 <= 13
      ? 'th'
      : (['th', 'st', 'nd', 'rd'][rank % 10] ?? 'th')
  return `${rank}${suffix}`
}

function deltaDuration(a: number, b: number): string {
  const seconds = Math.abs(a - b)
  return duration(seconds)
}

/**
 * One sentence saying why `route` sits where it does.
 *
 * Rank 1 is the backend's own `recommendation_reason` (or, when nothing is
 * recommended, its ineligibility). Every other rank names the criterion the
 * backend recorded against the route directly above, with both values, so
 * the reader can check the claim against the table.
 */
export function explainPosition(
  route: AnalysedRoute,
  previous: AnalysedRoute | null,
  analysis: RouteAnalysisResponse,
): string {
  if (!previous) {
    if (route.is_recommended) return analysis.recommendation_reason
    if (!route.eligible) {
      return `Ranked 1st, but it cannot be recommended: ${route.ineligibility_reasons.join('; ')}.`
    }
    return `${route.label} is ranked 1st.`
  }

  const m = route.metrics
  const p = previous.metrics
  const lead = `Ranked ${ordinal(route.rank)}, below ${previous.label}: `

  switch (route.separated_from_previous_by) {
    case 'eligibility':
      return (
        lead +
        `it cannot be recommended (${route.ineligibility_reasons.join('; ')}), ` +
        'and eligible routes always rank first.'
      )
    case 'severe_miles':
      return lead + `more Severe miles (${miles(m.severe_miles, 0)} vs ${miles(p.severe_miles, 0)}).`
    case 'high_miles':
      return (
        lead +
        `Severe miles tie (${miles(m.severe_miles, 0)}); more High miles ` +
        `(${miles(m.high_miles, 0)} vs ${miles(p.high_miles, 0)}).`
      )
    case 'average_risk':
      return (
        lead +
        'Severe and High miles tie; higher distance-weighted average risk ' +
        `(${averageRisk(m.average_risk)} vs ${averageRisk(p.average_risk)}).`
      )
    case 'duration_seconds':
      return (
        lead +
        'all three risk criteria tie; longer drive ' +
        `(${duration(m.duration_seconds)} vs ${duration(p.duration_seconds)}, ` +
        `+${deltaDuration(m.duration_seconds, p.duration_seconds)}).`
      )
    case 'unknown_miles':
      return (
        lead +
        'all four assessment criteria tie; more miles without a forecast ' +
        `(${miles(m.unknown_miles, 1)} vs ${miles(p.unknown_miles, 1)}).`
      )
    default:
      return lead + 'identical on every criterion, so the provider’s original order decides.'
  }
}

const SEVERITY: Record<RiskLevel, number> = {
  UNKNOWN: -1,
  LOW: 0,
  MODERATE: 1,
  HIGH: 2,
  SEVERE: 3,
  NO_TRAVEL: 4,
}

/**
 * The checkpoints that most threaten this route, worst first.
 *
 * Only levels above Low qualify -- a list of green checkpoints explains
 * nothing -- and UNKNOWN is excluded: it is an absence of information, not
 * a hazard. Ties keep route order so the list reads along the drive.
 */
export function worstCheckpoints(route: AnalysedRoute, limit = 3): Checkpoint[] {
  return route.checkpoints
    .filter((point) => SEVERITY[point.risk.level] > SEVERITY.LOW)
    .sort((a, b) => SEVERITY[b.risk.level] - SEVERITY[a.risk.level] || a.index - b.index)
    .slice(0, limit)
}

export interface RiskMileSegment {
  level: RiskLevel
  miles: number
  /** Share of the route, 0..1. */
  share: number
}

/** Miles by level for a stacked bar, in severity order with Unknown last. */
export function riskMileSegments(metrics: RouteMetrics): RiskMileSegment[] {
  const total = metrics.distance_miles > 0 ? metrics.distance_miles : 1
  const entries: Array<[RiskLevel, number]> = [
    ['LOW', metrics.low_miles],
    ['MODERATE', metrics.moderate_miles],
    ['HIGH', metrics.high_miles],
    ['SEVERE', metrics.severe_miles],
    ['NO_TRAVEL', metrics.no_travel_miles],
    ['UNKNOWN', metrics.unknown_miles],
  ]
  return entries
    .filter(([, value]) => value > 0)
    .map(([level, value]) => ({ level, miles: value, share: value / total }))
}

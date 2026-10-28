/**
 * Synthetic corridor-forecast fixtures. Deterministic, built in-process;
 * nothing here was captured from a provider.
 */

import type {
  AnalysedRoute,
  CorridorForecastResponse,
  CorridorFrame,
  CorridorFrameCheckpoint,
  RiskLevel,
} from '@/api/types'

const REFERENCE = Date.UTC(2026, 10, 2, 13)

function iso(hour: number): string {
  return new Date(REFERENCE + hour * 3_600_000).toISOString().replace('.000Z', '+00:00')
}

export function makeFrameCheckpoint(
  index: number,
  level: RiskLevel = 'LOW',
  overrides: Partial<CorridorFrameCheckpoint> = {},
): CorridorFrameCheckpoint {
  const unknown = level === 'UNKNOWN'
  return {
    index,
    weather: unknown
      ? null
      : {
          wind_mph: 12 + index,
          wind_gust_mph: 20 + index,
          rain_in_hr: 0,
          snow_in_hr: 0,
          forecast_time: null,
        },
    risk: {
      level,
      driver: unknown ? null : 'wind',
      base_level: level,
      wind_level: level,
      rain_level: unknown ? 'UNKNOWN' : 'LOW',
      snow_level: unknown ? 'UNKNOWN' : 'LOW',
      load_override_applied: false,
      partial_data: false,
      explanation: unknown
        ? 'No forecast was available for this checkpoint.'
        : `Wind ${12 + index}.0 mph (${level}). Overall ${level}.`,
    },
    ...overrides,
  }
}

export interface FrameSpec {
  /** Level for every checkpoint, or per-index overrides. */
  level?: RiskLevel
  levels?: Record<number, RiskLevel>
  available?: boolean
}

export function makeFrame(
  hour: number,
  checkpointIndexes: number[],
  spec: FrameSpec = {},
): CorridorFrame {
  const available = spec.available ?? true
  const checkpoints = checkpointIndexes.map((index) =>
    makeFrameCheckpoint(
      index,
      available ? (spec.levels?.[index] ?? spec.level ?? 'LOW') : 'UNKNOWN',
    ),
  )
  const worst = checkpoints.reduce<RiskLevel>((acc, point) => {
    const order: RiskLevel[] = ['LOW', 'MODERATE', 'HIGH', 'SEVERE', 'NO_TRAVEL']
    const a = order.indexOf(acc)
    const b = order.indexOf(point.risk.level)
    return b > a ? point.risk.level : acc
  }, 'LOW')
  return {
    hour,
    at: iso(hour),
    at_local: null,
    available,
    unavailable_reason: available ? null : 'outside_provider_horizon',
    summary: {
      low_miles: available ? 100 : 0,
      moderate_miles: 0,
      high_miles: 0,
      severe_miles: 0,
      no_travel_miles: 0,
      unknown_miles: available ? 0 : 100,
      average_risk: available ? 0 : null,
      max_risk: available ? worst : 'UNKNOWN',
      coverage_pct: available ? 100 : 0,
      blocked: false,
    },
    checkpoints,
  }
}

/**
 * A full 49-frame corridor for `route`. `specs` customises individual hours;
 * every other hour is calm and available.
 */
export function makeCorridorForecast(
  route: AnalysedRoute,
  specs: Record<number, FrameSpec> = {},
  overrides: Partial<CorridorForecastResponse> = {},
): CorridorForecastResponse {
  const indexes = route.checkpoints.map((point) => point.index)
  const frames = Array.from({ length: 49 }, (_, hour) =>
    makeFrame(hour, indexes, specs[hour] ?? {}),
  )
  return {
    route_id: route.route_id,
    reference_at: iso(0),
    reference_at_local: null,
    timezone: 'America/Denver',
    step_hours: 1,
    horizon_hours: 48,
    provider: 'open-meteo',
    load_weight_lb: 40_000,
    forecast_window: { start: iso(0), end: iso(48) },
    checkpoints: route.checkpoints.map((point) => ({
      index: point.index,
      latitude: point.latitude,
      longitude: point.longitude,
      distance_from_origin_miles: point.distance_from_origin_miles,
      segment_miles: point.segment_miles,
    })),
    frames,
    available_hours: frames.filter((frame) => frame.available).length,
    warnings: [],
    meta: { elapsed_ms: 1, checkpoints: indexes.length, frames: 49 },
    ...overrides,
  }
}

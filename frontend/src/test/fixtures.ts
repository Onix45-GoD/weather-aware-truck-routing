/**
 * Response builders for tests.
 *
 * Shaped from a real `POST /api/v1/route-analysis` response, so the tests
 * exercise the contract the backend actually produces rather than one
 * invented to match the components.
 *
 * These are test fixtures only. Nothing here is ever rendered at runtime —
 * the app has no demo mode and no canned analysis.
 */

import type {
  AnalysedRoute,
  Checkpoint,
  RiskLevel,
  RouteAnalysisResponse,
} from '@/api/types'

let checkpointSeed = 0

export function makeCheckpoint(
  overrides: Partial<Checkpoint> = {},
): Checkpoint {
  const index = overrides.index ?? checkpointSeed++
  return {
    index,
    latitude: 39.74 + index * 0.1,
    longitude: -104.99 + index * 0.4,
    distance_from_origin_miles: index * 25,
    segment_miles: 25,
    eta: new Date(Date.UTC(2026, 10, 2, 13 + index)).toISOString(),
    is_origin: index === 0,
    is_destination: false,
    weather: {
      wind_mph: 18,
      wind_gust_mph: 26,
      rain_in_hr: 0,
      snow_in_hr: 0,
      forecast_time: new Date(Date.UTC(2026, 10, 2, 13 + index)).toISOString(),
    },
    risk: {
      level: 'LOW',
      driver: 'wind',
      base_level: 'LOW',
      wind_level: 'LOW',
      rain_level: 'LOW',
      snow_level: 'LOW',
      load_override_applied: false,
      partial_data: false,
      explanation: 'Wind 18.0 mph (Low); Rain 0.00 in/hr (Low). Overall Low.',
    },
    ...overrides,
  }
}

export function makeRoute(overrides: Partial<AnalysedRoute> = {}): AnalysedRoute {
  const checkpoints = overrides.checkpoints ?? [
    makeCheckpoint({ index: 0, is_origin: true }),
    makeCheckpoint({ index: 1 }),
    makeCheckpoint({ index: 2, is_destination: true, segment_miles: 0 }),
  ]

  return {
    route_id: 'tomtom-0',
    label: 'Primary route',
    rank: 1,
    is_recommended: true,
    eligible: true,
    ineligibility_reasons: [],
    separated_from_previous_by: null,
    summary: {
      distance_miles: 1004.2,
      duration_seconds: 50_066,
      departure_at: '2026-11-02T13:00:00+00:00',
      arrival_at: '2026-11-03T02:54:26+00:00',
      arrival_at_local: '2026-11-02T19:54:26-07:00',
      eta_source: 'distance_proportional',
    },
    metrics: {
      distance_miles: 1004.2,
      duration_seconds: 50_066,
      low_miles: 1004.2,
      moderate_miles: 0,
      high_miles: 0,
      severe_miles: 0,
      no_travel_miles: 0,
      unknown_miles: 0,
      average_risk: 0,
      max_risk: 'LOW',
      coverage_pct: 100,
      no_travel_checkpoints: 0,
      blocked: false,
    },
    geometry: [
      [39.7392, -104.9903],
      [40.5, -98.0],
      [41.8781, -87.6298],
    ],
    geometry_detail: {
      returned_points: 3,
      source_points: 10_760,
      simplified: true,
      tolerance_miles: 0.005,
    },
    checkpoints,
    ...overrides,
  }
}

export function makeAnalysis(
  overrides: Partial<RouteAnalysisResponse> = {},
): RouteAnalysisResponse {
  const routes = overrides.routes ?? [makeRoute()]
  return {
    request: {
      origin: 'Denver, CO',
      destination: 'Chicago, IL',
      departure_at: '2026-11-02T13:00:00+00:00',
      departure_timezone: 'America/Denver',
      departure_at_local: '2026-11-02T06:00:00-07:00',
      effective_departure_at: '2026-11-02T13:00:00+00:00',
      effective_departure_at_local: '2026-11-02T06:00:00-07:00',
      forecast_offset_hours: 0,
      load_weight_lb: 40_000,
      checkpoint_interval_miles: 25,
    },
    origin: {
      label: 'Denver, CO',
      latitude: 39.7385,
      longitude: -104.9849,
      confidence: 1,
    },
    destination: {
      label: 'Chicago, IL',
      latitude: 41.8781,
      longitude: -87.6298,
      confidence: 1,
    },
    recommended_route_id: routes[0]?.route_id ?? null,
    recommendation_reason:
      'Primary route is recommended: it has the fewest Severe miles.',
    routes,
    warnings: [],
    meta: {
      routes_returned_by_provider: routes.length,
      routes_analysed: routes.length,
      providers: {
        geocoding: 'tomtom',
        routing: 'tomtom',
        weather: 'open-meteo',
      },
      risk_levels: [
        'LOW',
        'MODERATE',
        'HIGH',
        'SEVERE',
        'NO_TRAVEL',
        'UNKNOWN',
      ],
      elapsed_ms: 412,
    },
    ...overrides,
  }
}

/** Several alternatives, ranked, with the first recommended. */
export function makeRoutes(count: number): AnalysedRoute[] {
  return Array.from({ length: count }, (_unused, position) =>
    makeRoute({
      route_id: `tomtom-${position}`,
      label: position === 0 ? 'Primary route' : `Alternative ${position}`,
      rank: position + 1,
      is_recommended: position === 0,
      checkpoints: [
        makeCheckpoint({ index: 0, is_origin: true }),
        makeCheckpoint({ index: 1 }),
        makeCheckpoint({ index: 2, is_destination: true, segment_miles: 0 }),
      ],
      metrics: {
        ...makeRoute().metrics,
        distance_miles: 1000 + position * 120,
        duration_seconds: 50_000 + position * 7_000,
      },
    }),
  )
}

/** A route with a forecast gap, for the UNKNOWN / coverage paths. */
export function makeRouteWithMissingWeather(): AnalysedRoute {
  const unknownRisk: Checkpoint['risk'] = {
    level: 'UNKNOWN' as RiskLevel,
    driver: null,
    base_level: 'UNKNOWN',
    wind_level: 'UNKNOWN',
    rain_level: 'UNKNOWN',
    snow_level: 'UNKNOWN',
    load_override_applied: false,
    partial_data: false,
    explanation:
      'Wind unavailable (Unknown); Rain unavailable (Unknown). ' +
      'Overall Unknown: no forecast available at this checkpoint.',
  }

  return makeRoute({
    checkpoints: [
      makeCheckpoint({ index: 0, is_origin: true }),
      makeCheckpoint({ index: 1, weather: null, risk: unknownRisk }),
      makeCheckpoint({ index: 2, is_destination: true, segment_miles: 0 }),
    ],
    metrics: {
      ...makeRoute().metrics,
      low_miles: 975,
      unknown_miles: 25,
      coverage_pct: 97.5,
    },
  })
}

/** Every route blocked by No Travel conditions. */
export function makeBlockedAnalysis(): RouteAnalysisResponse {
  const blocked = makeRoute({
    is_recommended: false,
    eligible: false,
    ineligibility_reasons: ['No Travel conditions over 50.0 mi of this route'],
    metrics: {
      ...makeRoute().metrics,
      no_travel_miles: 50,
      low_miles: 954.2,
      max_risk: 'NO_TRAVEL',
      blocked: true,
      no_travel_checkpoints: 2,
    },
  })

  return makeAnalysis({
    routes: [blocked],
    recommended_route_id: null,
    recommendation_reason:
      'No route can be recommended: every option encounters No Travel ' +
      'conditions at this departure time. Consider delaying departure.',
    warnings: [
      {
        code: 'NO_ELIGIBLE_ROUTE',
        message:
          'No route can be recommended: every option encounters No Travel ' +
          'conditions at this departure time.',
        route_id: null,
      },
    ],
  })
}

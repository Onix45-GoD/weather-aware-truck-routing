/**
 * Types for `POST /api/v1/route-analysis`.
 *
 * These mirror the Django response exactly -- field names were taken from a
 * live analysis, not from the design mockups. Anything the mockups show that
 * the API does not return is absent here on purpose.
 *
 * Nullability is explicit throughout. The backend sends `null` rather than
 * omitting a key, so optionality in these types means "the server said it has
 * no value", never "the key might be missing".
 */

/** Risk classification. Decided entirely by the backend domain engine. */
export const RISK_LEVELS = [
  'LOW',
  'MODERATE',
  'HIGH',
  'SEVERE',
  'NO_TRAVEL',
  'UNKNOWN',
] as const

export type RiskLevel = (typeof RISK_LEVELS)[number]

export const CHECKPOINT_INTERVALS = [10, 25, 50] as const
export type CheckpointInterval = (typeof CHECKPOINT_INTERVALS)[number]

/** How checkpoint ETAs were derived. */
export type EtaSource = 'provider_segments' | 'distance_proportional'

// --- request ---------------------------------------------------------------

export interface RouteAnalysisRequest {
  origin: string
  destination: string
  /**
   * ISO 8601. Either carries a UTC offset, or is local wall-clock time sent
   * together with `departure_timezone`. A naive value with no timezone is
   * rejected by the server rather than guessed.
   */
  departure_at: string
  /** IANA name, e.g. `America/Denver`. Required when `departure_at` is naive. */
  departure_timezone?: string
  load_weight_lb: number
  checkpoint_interval_miles: CheckpointInterval
  /**
   * Shifts the departure later by this many hours and re-runs the whole
   * analysis -- routing, ETAs, weather and ranking. It can change the
   * recommendation. This is NOT a display-only forecast scrubber.
   */
  forecast_offset_hours?: number
}

// --- response --------------------------------------------------------------

export interface NormalisedRequest {
  origin: string
  destination: string
  departure_at: string
  departure_timezone: string | null
  departure_at_local: string | null
  effective_departure_at: string
  effective_departure_at_local: string | null
  forecast_offset_hours: number
  load_weight_lb: number
  checkpoint_interval_miles: number
}

export interface ResolvedPlace {
  label: string
  latitude: number
  longitude: number
  /** 0-1 match confidence, or null when the provider reported none. */
  confidence: number | null
}

export interface WeatherSample {
  wind_mph: number | null
  wind_gust_mph: number | null
  rain_in_hr: number | null
  snow_in_hr: number | null
  forecast_time: string | null
}

export interface CheckpointRisk {
  level: RiskLevel
  /** Which condition drove the level: `wind` | `rain` | `snow`, or null. */
  driver: string | null
  base_level: RiskLevel
  wind_level: RiskLevel
  rain_level: RiskLevel
  snow_level: RiskLevel
  /** True when a cargo-weight rule escalated the wind classification. */
  load_override_applied: boolean
  /** True when some measurements were missing but others were usable. */
  partial_data: boolean
  explanation: string
}

export interface Checkpoint {
  index: number
  latitude: number
  longitude: number
  distance_from_origin_miles: number
  /** Miles this checkpoint governs. The destination owns zero. */
  segment_miles: number
  eta: string
  is_origin: boolean
  is_destination: boolean
  /** Null when no forecast was obtained -- NOT zero conditions. */
  weather: WeatherSample | null
  risk: CheckpointRisk
}

export interface RouteSummary {
  distance_miles: number
  duration_seconds: number
  departure_at: string
  arrival_at: string
  arrival_at_local: string | null
  eta_source: EtaSource
}

export interface RouteMetrics {
  distance_miles: number
  duration_seconds: number
  low_miles: number
  moderate_miles: number
  high_miles: number
  severe_miles: number
  no_travel_miles: number
  unknown_miles: number
  /** Distance-weighted mean of risk scores 0-4. Null when nothing is known. */
  average_risk: number | null
  max_risk: RiskLevel
  /** Percentage of route miles with a usable forecast. */
  coverage_pct: number
  no_travel_checkpoints: number
  blocked: boolean
}

export interface GeometryDetail {
  returned_points: number
  source_points: number
  simplified: boolean
  tolerance_miles: number
}

export interface AnalysedRoute {
  route_id: string
  label: string
  rank: number
  is_recommended: boolean
  eligible: boolean
  ineligibility_reasons: string[]
  /** Which ranking criterion separated this route from the one above it. */
  separated_from_previous_by: string | null
  summary: RouteSummary
  metrics: RouteMetrics
  /** `[latitude, longitude]` pairs, simplified for display. */
  geometry: Array<[number, number]>
  geometry_detail: GeometryDetail
  checkpoints: Checkpoint[]
}

export interface AnalysisWarning {
  code: string
  message: string
  route_id: string | null
}

export interface AnalysisMeta {
  routes_returned_by_provider: number
  routes_analysed: number
  providers: Record<string, string>
  risk_levels: RiskLevel[]
  elapsed_ms: number
}

export interface RouteAnalysisResponse {
  request: NormalisedRequest
  origin: ResolvedPlace
  destination: ResolvedPlace
  /** Null when no route is eligible -- the UI must not invent one. */
  recommended_route_id: string | null
  recommendation_reason: string
  /** Ranked. Ineligible routes are included so the UI can explain them. */
  routes: AnalysedRoute[]
  warnings: AnalysisWarning[]
  meta: AnalysisMeta
}

// --- errors ----------------------------------------------------------------

/** Error codes the backend can return. */
export type ApiErrorCode =
  | 'INVALID_REQUEST'
  | 'GEOCODING_NO_RESULTS'
  | 'LOCATION_AMBIGUOUS'
  | 'ROUTING_NO_ROUTES'
  | 'PROVIDER_RATE_LIMITED'
  | 'PROVIDER_TIMEOUT'
  | 'PROVIDER_UNAVAILABLE'
  | 'PROVIDER_INVALID_RESPONSE'
  | 'PROVIDER_AUTH_FAILED'
  | 'PROVIDER_MISCONFIGURED'
  | 'INTERNAL_ERROR'
  // Client-side only -- the request never reached the server.
  | 'NETWORK_ERROR'

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    /** Request field responsible, when the server identified one. */
    field: string | null
    /** Per-field messages for `INVALID_REQUEST`. */
    details: Record<string, string[]> | null
  }
}

export interface HealthResponse {
  status: string
  /** Provider names and credential *presence* flags -- never a value. */
  providers: Record<string, string | boolean | null>
}

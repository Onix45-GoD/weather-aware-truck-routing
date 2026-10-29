import type { RouteAnalysisRequest } from '@/api/types'
import type { TripFormValues } from '@/features/route-analysis/TripForm'
import { DEFAULT_TIMEZONE } from '@/lib/timezones'

const EXAMPLE = {
  origin: 'Denver, CO',
  destination: 'Chicago, IL',
  loadWeightLb: 40_000,
  checkpointIntervalMiles: 25 as const,
}

/**
 * Wall-clock `YYYY-MM-DDTHH:mm` for an instant *in a named zone*.
 *
 * `toISOString` would give UTC and the browser's own zone is irrelevant:
 * the example departs Denver, so the departure is expressed in Denver
 * time and the server applies that zone's rules.
 */
export function wallClockIn(instant: Date, timeZone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(instant)
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? '00'
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}

/** Denver → Chicago, leaving two hours from now on the hour, 40,000 lb. */
export function exampleTrip(now: Date = new Date()): {
  values: TripFormValues
  payload: RouteAnalysisRequest
} {
  const departure = new Date(now.getTime() + 2 * 60 * 60 * 1000)
  departure.setMinutes(0, 0, 0)
  const departureLocal = wallClockIn(departure, DEFAULT_TIMEZONE)
  return {
    values: {
      origin: EXAMPLE.origin,
      destination: EXAMPLE.destination,
      departureLocal,
      departureTimezone: DEFAULT_TIMEZONE,
      loadWeightLb: String(EXAMPLE.loadWeightLb),
      checkpointIntervalMiles: EXAMPLE.checkpointIntervalMiles,
    },
    payload: {
      origin: EXAMPLE.origin,
      destination: EXAMPLE.destination,
      departure_at: departureLocal,
      departure_timezone: DEFAULT_TIMEZONE,
      load_weight_lb: EXAMPLE.loadWeightLb,
      checkpoint_interval_miles: EXAMPLE.checkpointIntervalMiles,
    },
  }
}

const DISMISSED_KEY = 'wr.onboarding.dismissed'

/** Whether the visitor has dismissed the guide before. Storage may be unavailable. */
export function onboardingDismissed(): boolean {
  try {
    return window.localStorage.getItem(DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

export function rememberOnboardingDismissed(): void {
  try {
    window.localStorage.setItem(DISMISSED_KEY, '1')
  } catch {
    // A private window or blocked storage: the panel simply returns next visit.
  }
}

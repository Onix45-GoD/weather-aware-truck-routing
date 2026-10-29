import type { TripFormValues } from './TripForm'

const KEY = 'wr.trip'

const FIELDS: ReadonlyArray<keyof TripFormValues> = [
  'origin',
  'destination',
  'departureLocal',
  'departureTimezone',
  'loadWeightLb',
  'checkpointIntervalMiles',
]

/**
 * The last trip the user typed, so a refresh does not empty the form.
 *
 * Only the inputs are kept -- never a result -- and nothing is re-run on
 * load: the user still presses Analyze, so a reload costs no provider quota.
 * Storage may be unavailable (private window, blocked site data); every
 * access is guarded and the form then simply starts from its defaults.
 */
export function loadStoredTrip(): Partial<TripFormValues> | null {
  try {
    const raw = window.localStorage.getItem(KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    const values: Partial<TripFormValues> = {}
    for (const field of FIELDS) {
      const value = (parsed as Record<string, unknown>)[field]
      if (field === 'checkpointIntervalMiles') {
        if (value === 10 || value === 25 || value === 50) values[field] = value
      } else if (typeof value === 'string') {
        values[field] = value
      }
    }
    return values
  } catch {
    return null
  }
}

export function storeTrip(values: TripFormValues): void {
  try {
    const subset: Partial<TripFormValues> = {}
    for (const field of FIELDS) (subset as Record<string, unknown>)[field] = values[field]
    window.localStorage.setItem(KEY, JSON.stringify(subset))
  } catch {
    // Nothing to do: the form still works, it just will not be remembered.
  }
}

export function clearStoredTrip(): void {
  try {
    window.localStorage.removeItem(KEY)
  } catch {
    // As above.
  }
}

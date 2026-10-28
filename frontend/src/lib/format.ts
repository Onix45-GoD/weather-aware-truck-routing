/**
 * Presentation formatting.
 *
 * Every function here answers "how do I show this?", never "what is this?".
 * Risk levels, mileage and rankings all arrive already decided by the
 * backend.
 */

/** `1,023 mi` */
export function miles(value: number, digits = 0): string {
  return `${value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} mi`
}

/** `16h 24m` */
export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds / 60))
  const hours = Math.floor(total / 60)
  const minutes = total % 60
  if (hours === 0) return `${minutes}m`
  return `${hours}h ${String(minutes).padStart(2, '0')}m`
}

/** `82%` */
export function percent(value: number, digits = 0): string {
  return `${value.toFixed(digits)}%`
}

/**
 * Average risk is a 0–4 ordinal mean. Showing the raw number means nothing to
 * a driver, so it is expressed as a share of the worst possible score.
 */
export function averageRisk(value: number | null): string {
  if (value === null) return '—'
  return `${Math.round((value / 4) * 100)}%`
}

/** A timestamp in a chosen IANA zone: `6:00 AM`. */
export function clockTime(iso: string, timeZone?: string | null): string {
  try {
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
      ...(timeZone ? { timeZone } : {}),
    })
  } catch {
    return iso
  }
}

/** `Mon 2 Nov, 6:00 AM` */
export function dateTime(iso: string, timeZone?: string | null): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      hour: 'numeric',
      minute: '2-digit',
      ...(timeZone ? { timeZone } : {}),
    })
  } catch {
    return iso
  }
}

/** Short zone abbreviation for a label, e.g. `CST`. */
export function zoneAbbreviation(iso: string, timeZone?: string | null): string {
  if (!timeZone) return 'UTC'
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone,
      timeZoneName: 'short',
    }).formatToParts(new Date(iso))
    return parts.find((part) => part.type === 'timeZoneName')?.value ?? ''
  } catch {
    return ''
  }
}

/**
 * A measurement that may be absent.
 *
 * Missing weather renders as an em dash, never `0`. Zero means "calm and
 * dry", which is a materially different claim from "we do not know".
 */
export function measurement(
  value: number | null | undefined,
  unit: string,
  digits = 1,
): string {
  if (value === null || value === undefined) return '—'
  return `${value.toFixed(digits)} ${unit}`
}

/** `40,000 lb` */
export function pounds(value: number): string {
  return `${value.toLocaleString()} lb`
}

/** Compass point for a wind direction in degrees ("from"). */
export function compassPoint(degrees: number | null): string | null {
  if (degrees === null || !Number.isFinite(degrees)) return null
  const points = [
    'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
  ]
  const index = Math.round((((degrees % 360) + 360) % 360) / 22.5) % 16
  return points[index] ?? null
}

/**
 * IANA timezone options for the departure picker.
 *
 * The browser knows the full list, so no endpoint is needed to serve one.
 * `Intl.supportedValuesOf` is widely available but not universal, so a
 * curated North-America-first list is the fallback — this is a US trucking
 * tool, and an empty select would be worse than a short one.
 */

export interface TimezoneOption {
  value: string
  label: string
}

/** Common North American zones, plus a few others, for the fallback path. */
const FALLBACK_ZONES = [
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'America/Anchorage',
  'Pacific/Honolulu',
  'America/Toronto',
  'America/Vancouver',
  'America/Mexico_City',
  'UTC',
  'Europe/London',
  'Europe/Berlin',
  'Asia/Tokyo',
]

/** Zones shown first, because most trips will use one of them. */
const PRIORITY = new Set([
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Phoenix',
  'America/Los_Angeles',
  'UTC',
])

function abbreviation(zone: string): string {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      timeZoneName: 'short',
    }).formatToParts(new Date())
    return parts.find((part) => part.type === 'timeZoneName')?.value ?? ''
  } catch {
    return ''
  }
}

function label(zone: string): string {
  const short = abbreviation(zone)
  return short ? `${zone} (${short})` : zone
}

function supportedZones(): string[] {
  const intl = Intl as typeof Intl & {
    supportedValuesOf?: (key: string) => string[]
  }
  try {
    const zones = intl.supportedValuesOf?.('timeZone')
    if (zones && zones.length > 0) return zones
  } catch {
    // Older engines throw rather than returning undefined.
  }
  return FALLBACK_ZONES
}

/**
 * The form default. A US trucking tool starts in a US zone -- the one the
 * default origin (Denver) is in -- rather than wherever the browser is; a
 * dispatcher in another country still plans the trip in the truck's zone.
 */
export const DEFAULT_TIMEZONE = 'America/Denver'

/** The viewer's own timezone, listed first so it is one click away. */
export function browserTimezone(): string {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone
    if (zone) return zone
  } catch {
    // Fall through.
  }
  return 'America/Denver'
}

export function timezoneOptions(): TimezoneOption[] {
  const zones = supportedZones()
  const current = browserTimezone()

  const seen = new Set<string>()
  const ordered: string[] = []

  for (const zone of [DEFAULT_TIMEZONE, current, ...zones.filter((z) => PRIORITY.has(z))]) {
    if (zone && !seen.has(zone)) {
      seen.add(zone)
      ordered.push(zone)
    }
  }
  for (const zone of zones) {
    if (!seen.has(zone)) {
      seen.add(zone)
      ordered.push(zone)
    }
  }

  return ordered.map((zone) => ({ value: zone, label: label(zone) }))
}

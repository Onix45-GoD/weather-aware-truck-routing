import { dateTime, zoneAbbreviation } from '@/lib/format'

/**
 * Human label for a frame's instant in the trip's zone, e.g.
 * `Mon 2 Nov, 6:00 PM MST`. Null (no frame) renders as an em dash so a
 * missing value never reads as a time.
 */
export function frameLabel(
  at: string | null | undefined,
  timeZone?: string | null,
): string {
  if (!at) return '—'
  const zone = zoneAbbreviation(at, timeZone)
  return `${dateTime(at, timeZone)}${zone ? ` ${zone}` : ''}`
}

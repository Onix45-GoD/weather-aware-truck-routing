import { DEFAULT_TIMEZONE } from '@/lib/timezones'

import type { TripFormValues } from './TripForm'

function defaultDeparture(): string {
  const when = new Date(Date.now() + 2 * 60 * 60 * 1000)
  when.setMinutes(0, 0, 0)
  // `toISOString` would convert to UTC; we want the *local* wall clock.
  const pad = (value: number) => String(value).padStart(2, '0')
  return (
    `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}` +
    `T${pad(when.getHours())}:${pad(when.getMinutes())}`
  )
}

export function defaultTripValues(): TripFormValues {
  return {
    origin: 'Denver, CO',
    destination: 'Chicago, IL',
    departureLocal: defaultDeparture(),
    // A US trucking tool defaults to a US zone -- the one the default
    // origin is in -- not to wherever the browser happens to be.
    departureTimezone: DEFAULT_TIMEZONE,
    loadWeightLb: '40000',
    checkpointIntervalMiles: 25,
  }
}

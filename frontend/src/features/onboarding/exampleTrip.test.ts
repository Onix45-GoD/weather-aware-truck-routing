import { afterEach, describe, expect, it } from 'vitest'

import {
  exampleTrip,
  onboardingDismissed,
  rememberOnboardingDismissed,
  wallClockIn,
} from './exampleTrip'

describe('wallClockIn', () => {
  it('renders an instant as the named zone’s wall clock, not UTC or the browser’s', () => {
    // 2026-11-02T13:00Z is 06:00 in Denver (MST after the DST change).
    expect(wallClockIn(new Date('2026-11-02T13:00:00Z'), 'America/Denver')).toBe('2026-11-02T06:00')
    expect(wallClockIn(new Date('2026-11-02T13:00:00Z'), 'America/New_York')).toBe('2026-11-02T08:00')
  })
})

describe('exampleTrip', () => {
  it('departs Denver two hours from now, on the hour, in Denver time', () => {
    const now = new Date('2026-11-02T13:25:00Z')
    const { values, payload } = exampleTrip(now)
    expect(values.origin).toBe('Denver, CO')
    expect(payload.departure_timezone).toBe('America/Denver')
    expect(payload.departure_at).toBe('2026-11-02T08:00') // 15:00Z = 08:00 MST
    expect(payload.departure_at).toBe(values.departureLocal)
    expect(payload.load_weight_lb).toBe(40_000)
    expect(payload.checkpoint_interval_miles).toBe(25)
    expect(payload).not.toHaveProperty('forecast_offset_hours')
  })
})

describe('onboarding dismissal', () => {
  afterEach(() => {
    window.localStorage.clear()
  })

  it('is remembered in local storage', () => {
    expect(onboardingDismissed()).toBe(false)
    rememberOnboardingDismissed()
    expect(onboardingDismissed()).toBe(true)
  })
})

import { afterEach, describe, expect, it } from 'vitest'

import { clearStoredTrip, loadStoredTrip, storeTrip } from './tripStorage'

const values = {
  origin: 'Boise, ID',
  destination: 'Reno, NV',
  departureLocal: '2026-11-03T05:00',
  departureTimezone: 'America/Boise',
  loadWeightLb: '32000',
  checkpointIntervalMiles: 10 as const,
}

afterEach(() => {
  window.localStorage.clear()
})

describe('trip storage', () => {
  it('is empty on a first visit', () => {
    expect(loadStoredTrip()).toBeNull()
  })

  it('round-trips every form field', () => {
    storeTrip(values)
    expect(loadStoredTrip()).toEqual(values)
  })

  it('ignores corrupt or foreign data instead of throwing', () => {
    window.localStorage.setItem('wr.trip', '{not json')
    expect(loadStoredTrip()).toBeNull()
    window.localStorage.setItem('wr.trip', JSON.stringify({ origin: 5, checkpointIntervalMiles: 17, extra: 'x' }))
    expect(loadStoredTrip()).toEqual({})
  })

  it('clears on request', () => {
    storeTrip(values)
    clearStoredTrip()
    expect(loadStoredTrip()).toBeNull()
  })
})

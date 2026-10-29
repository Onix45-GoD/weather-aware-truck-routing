import { describe, expect, it } from 'vitest'

import { makeRoute } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { checkpointSeries } from './series'

const route = makeRoute()

describe('checkpointSeries', () => {
  it('is null without frames or a selection', () => {
    expect(checkpointSeries(null, 1)).toBeNull()
    expect(checkpointSeries(makeCorridorForecast(route).frames, null)).toBeNull()
  })

  it('re-indexes the frames into one 49-hour series for the checkpoint', () => {
    const data = makeCorridorForecast(route, {
      12: { levels: { 1: 'SEVERE' } },
      40: { available: false },
    })
    const series = checkpointSeries(data.frames, 1)!
    expect(series).toHaveLength(49)
    expect(series.map((h) => h.hour)).toEqual(data.frames.map((f) => f.hour))
    expect(series[12]!.risk?.level).toBe('SEVERE')
    expect(series[11]!.risk?.level).toBe('LOW')
    expect(series[40]!.available).toBe(false)
    expect(series[40]!.weather).toBeNull()
    expect(series[40]!.risk?.level).toBe('UNKNOWN')
  })

  it('leaves risk null when the frame has no entry for the checkpoint', () => {
    const data = makeCorridorForecast(route)
    const series = checkpointSeries(data.frames, 999)!
    expect(series[0]!.risk).toBeNull()
    expect(series[0]!.weather).toBeNull()
  })
})

import { describe, expect, it } from 'vitest'

import { makeCheckpoint, makeRoute, makeRoutes } from '@/test/fixtures'

import {
  checkpointPoints,
  riskSegments,
  routeLines,
  routesBounds,
} from './geojson'

describe('routeLines', () => {
  it('flips [lat, lng] into GeoJSON [lng, lat] order', () => {
    const route = makeRoute({
      geometry: [
        [39.7392, -104.9903],
        [41.8781, -87.6298],
      ],
    })

    const [feature] = routeLines([route]).features
    // Longitude first, or Denver lands in the Southern Ocean.
    expect(feature?.geometry.coordinates[0]).toEqual([-104.9903, 39.7392])
  })

  it('carries the properties the map styles on', () => {
    const [feature] = routeLines([makeRoute()]).features
    expect(feature?.properties).toMatchObject({
      routeId: 'tomtom-0',
      isRecommended: true,
      eligible: true,
      rank: 1,
    })
  })

  it('emits one feature per route', () => {
    expect(routeLines(makeRoutes(3)).features).toHaveLength(3)
  })

  it('skips geometry too short to draw', () => {
    const degenerate = makeRoute({ geometry: [[39.7, -104.9]] })
    expect(routeLines([degenerate]).features).toHaveLength(0)
  })

  it('handles an empty analysis', () => {
    expect(routeLines([]).features).toHaveLength(0)
  })
})

describe('riskSegments', () => {
  it('produces one segment per checkpoint interval, not per checkpoint', () => {
    // Forward attribution: the last checkpoint owns no forward miles, so
    // n checkpoints yield n-1 drawable segments.
    const route = makeRoute()
    expect(riskSegments(route).features).toHaveLength(
      route.checkpoints.length - 1,
    )
  })

  it('colours each segment by the checkpoint that enters it', () => {
    const route = makeRoute({
      checkpoints: [
        makeCheckpoint({
          index: 0,
          is_origin: true,
          risk: { ...makeCheckpoint().risk, level: 'SEVERE' },
        }),
        makeCheckpoint({ index: 1 }),
        makeCheckpoint({ index: 2, is_destination: true }),
      ],
    })

    const [first] = riskSegments(route).features
    expect(first?.properties.level).toBe('SEVERE')
  })

  it('returns nothing when there is too little to draw', () => {
    const route = makeRoute({ checkpoints: [makeCheckpoint({ index: 0 })] })
    expect(riskSegments(route).features).toHaveLength(0)
  })
})

describe('checkpointPoints', () => {
  it('emits one point per checkpoint with its risk level', () => {
    const collection = checkpointPoints(makeRoute())
    expect(collection.features).toHaveLength(3)
    expect(collection.features[0]?.properties.level).toBe('LOW')
  })

  it('uses GeoJSON coordinate order', () => {
    const [feature] = checkpointPoints(makeRoute()).features
    const checkpoint = makeRoute().checkpoints[0]!
    expect(feature?.geometry.coordinates).toEqual([
      checkpoint.longitude,
      checkpoint.latitude,
    ])
  })

  it('preserves an UNKNOWN level rather than defaulting it', () => {
    const route = makeRoute({
      checkpoints: [
        makeCheckpoint({
          index: 0,
          weather: null,
          risk: { ...makeCheckpoint().risk, level: 'UNKNOWN' },
        }),
      ],
    })
    expect(checkpointPoints(route).features[0]?.properties.level).toBe(
      'UNKNOWN',
    )
  })
})

describe('routesBounds', () => {
  it('spans every route', () => {
    const bounds = routesBounds(makeRoutes(2))
    expect(bounds).not.toBeNull()

    const [west, south, east, north] = bounds!
    expect(west).toBeLessThan(east)
    expect(south).toBeLessThan(north)
    expect(west).toBeCloseTo(-104.9903, 3)
    expect(east).toBeCloseTo(-87.6298, 3)
  })

  it('returns null when there is nothing to fit', () => {
    expect(routesBounds([])).toBeNull()
  })
})

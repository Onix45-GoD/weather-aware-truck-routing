import { describe, expect, it } from 'vitest'

import type { RiskLevel } from '@/api/types'
import { makeRoute } from '@/test/fixtures'

import { corridorPoints, corridorSegments, riskSegments } from './geojson'

const route = makeRoute()

function levels(entries: Array<[number, RiskLevel]>): Map<number, RiskLevel> {
  return new Map(entries)
}

describe('corridorSegments', () => {
  it('uses the same forward-attributed pieces as the ETA risk line', () => {
    const base = riskSegments(route)
    const frame = corridorSegments(route, levels([]))
    expect(frame.features).toHaveLength(base.features.length)
    frame.features.forEach((feature, i) => {
      expect(feature.geometry).toEqual(base.features[i]!.geometry)
      expect(feature.properties.index).toBe(base.features[i]!.properties.index)
    })
  })

  it('colours each piece by the frame level of the checkpoint that governs it', () => {
    const frame = corridorSegments(
      route,
      levels([
        [0, 'LOW'],
        [1, 'SEVERE'],
      ]),
    )
    const byIndex = new Map(frame.features.map((f) => [f.properties.index, f.properties.level]))
    expect(byIndex.get(0)).toBe('LOW')
    expect(byIndex.get(1)).toBe('SEVERE')
  })

  it('treats a checkpoint the frame has no level for as UNKNOWN, never LOW', () => {
    const frame = corridorSegments(route, levels([[0, 'LOW']]))
    const missing = frame.features.filter((f) => f.properties.index !== 0)
    expect(missing.length).toBeGreaterThan(0)
    for (const feature of missing) expect(feature.properties.level).toBe('UNKNOWN')
  })
})

describe('corridorPoints', () => {
  it('emits one halo per checkpoint in [lng, lat] order', () => {
    const halos = corridorPoints(route, levels([[2, 'HIGH']]))
    expect(halos.features).toHaveLength(route.checkpoints.length)
    const second = halos.features[2]!
    expect(second.geometry.coordinates).toEqual([
      route.checkpoints[2]!.longitude,
      route.checkpoints[2]!.latitude,
    ])
    expect(second.properties.level).toBe('HIGH')
    expect(halos.features[0]!.properties.level).toBe('UNKNOWN')
  })
})

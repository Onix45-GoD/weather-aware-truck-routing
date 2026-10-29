import { describe, expect, it } from 'vitest'

import { makeAnalysis, makeCheckpoint, makeRoute, makeRoutes } from '@/test/fixtures'

import {
  criterionColumn,
  explainPosition,
  riskMileSegments,
  worstCheckpoints,
} from './ranking'

describe('criterionColumn', () => {
  it('maps every backend criterion to a table column, or none', () => {
    expect(criterionColumn('severe_miles')).toBe('severe')
    expect(criterionColumn('high_miles')).toBe('high')
    expect(criterionColumn('average_risk')).toBe('average')
    expect(criterionColumn('duration_seconds')).toBe('duration')
    expect(criterionColumn('unknown_miles')).toBe('coverage')
    expect(criterionColumn('eligibility')).toBe('status')
    expect(criterionColumn('provider_order')).toBeNull()
    expect(criterionColumn(null)).toBeNull()
  })
})

describe('explainPosition', () => {
  const analysis = makeAnalysis({ routes: makeRoutes(3) })
  const [first, second] = analysis.routes as [typeof analysis.routes[0], typeof analysis.routes[0]]

  it('uses the backend sentence verbatim for the recommended route', () => {
    expect(explainPosition(first, null, analysis)).toBe(analysis.recommendation_reason)
  })

  it('names the deciding criterion and both values for lower ranks', () => {
    const slower = { ...second, separated_from_previous_by: 'duration_seconds' as const }
    const text = explainPosition(slower, first, analysis)
    expect(text).toMatch(/^Ranked 2nd, below Primary route/)
    expect(text).toMatch(/all three risk criteria tie; longer drive/)
    expect(text).toMatch(/\+1h 57m/) // 57 000 s vs 50 000 s
  })

  it('shows Severe mile counts when that is what decided it', () => {
    const worse = {
      ...second,
      separated_from_previous_by: 'severe_miles' as const,
      metrics: { ...second.metrics, severe_miles: 42 },
    }
    expect(explainPosition(worse, first, analysis)).toMatch(/more Severe miles \(42 mi vs 0 mi\)/)
  })

  it('explains an ineligible route by its reasons', () => {
    const blocked = {
      ...second,
      eligible: false,
      separated_from_previous_by: 'eligibility' as const,
      ineligibility_reasons: ['No Travel conditions over 12.0 mi of this route'],
    }
    expect(explainPosition(blocked, first, analysis)).toMatch(
      /cannot be recommended \(No Travel conditions over 12.0 mi of this route\)/,
    )
  })

  it('handles a tie on every criterion', () => {
    const twin = { ...second, separated_from_previous_by: 'provider_order' as const }
    expect(explainPosition(twin, first, analysis)).toMatch(/provider’s original order decides/)
  })

  it('handles a first-ranked route that is not recommendable', () => {
    const noRec = makeAnalysis({ recommended_route_id: null })
    const route = { ...noRec.routes[0]!, is_recommended: false, eligible: false, ineligibility_reasons: ['x'] }
    expect(explainPosition(route, null, noRec)).toMatch(/Ranked 1st, but it cannot be recommended: x/)
  })
})

describe('worstCheckpoints', () => {
  it('lists checkpoints above Low, worst first, ignoring Unknown', () => {
    const route = makeRoute({
      checkpoints: [
        makeCheckpoint({ index: 0, risk: { ...makeCheckpoint().risk, level: 'LOW' } }),
        makeCheckpoint({ index: 1, risk: { ...makeCheckpoint().risk, level: 'HIGH' } }),
        makeCheckpoint({ index: 2, risk: { ...makeCheckpoint().risk, level: 'UNKNOWN' } }),
        makeCheckpoint({ index: 3, risk: { ...makeCheckpoint().risk, level: 'SEVERE' } }),
        makeCheckpoint({ index: 4, risk: { ...makeCheckpoint().risk, level: 'MODERATE' } }),
      ],
    })
    expect(worstCheckpoints(route).map((c) => c.index)).toEqual([3, 1, 4])
    expect(worstCheckpoints(route, 1).map((c) => c.index)).toEqual([3])
  })

  it('is empty for an all-Low route', () => {
    expect(worstCheckpoints(makeRoute())).toEqual([])
  })
})

describe('riskMileSegments', () => {
  it('drops empty levels and reports shares of the route', () => {
    const route = makeRoute({
      metrics: {
        ...makeRoute().metrics,
        distance_miles: 100,
        low_miles: 60,
        moderate_miles: 0,
        high_miles: 25,
        severe_miles: 0,
        no_travel_miles: 0,
        unknown_miles: 15,
      },
    })
    expect(riskMileSegments(route.metrics)).toEqual([
      { level: 'LOW', miles: 60, share: 0.6 },
      { level: 'HIGH', miles: 25, share: 0.25 },
      { level: 'UNKNOWN', miles: 15, share: 0.15 },
    ])
  })
})

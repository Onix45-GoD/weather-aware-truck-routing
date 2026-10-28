/**
 * Turning API results into GeoJSON for MapLibre.
 *
 * Pure functions, no map instance, so they are testable without a WebGL
 * context — which jsdom does not have.
 *
 * Note the coordinate order flip: the API sends `[latitude, longitude]`
 * (natural for a table), GeoJSON wants `[longitude, latitude]`. Getting this
 * backwards puts Denver in Antarctica, so it happens in exactly one place.
 */

import type { AnalysedRoute, Checkpoint, RiskLevel } from '@/api/types'

export interface RouteLineProperties {
  routeId: string
  label: string
  isRecommended: boolean
  eligible: boolean
  rank: number
}

export interface CheckpointProperties {
  routeId: string
  index: number
  level: RiskLevel
  mile: number
  eta: string
  isOrigin: boolean
  isDestination: boolean
}

type Feature<G, P> = { type: 'Feature'; geometry: G; properties: P }
type LineString = { type: 'LineString'; coordinates: Array<[number, number]> }
type Point = { type: 'Point'; coordinates: [number, number] }

export interface FeatureCollection<G, P> {
  type: 'FeatureCollection'
  features: Array<Feature<G, P>>
}

function toLngLat(point: readonly [number, number]): [number, number] {
  return [point[1], point[0]]
}

export function routeLines(
  routes: AnalysedRoute[],
): FeatureCollection<LineString, RouteLineProperties> {
  return {
    type: 'FeatureCollection',
    features: routes
      .filter((route) => route.geometry.length >= 2)
      .map((route) => ({
        type: 'Feature',
        geometry: {
          type: 'LineString',
          coordinates: route.geometry.map(toLngLat),
        },
        properties: {
          routeId: route.route_id,
          label: route.label,
          isRecommended: route.is_recommended,
          eligible: route.eligible,
          rank: route.rank,
        },
      })),
  }
}

/**
 * The selected route split into one segment per checkpoint, coloured by that
 * checkpoint's risk.
 *
 * Forward attribution (backend D6) says a checkpoint governs the stretch
 * *ahead* of it, so each segment runs from its own checkpoint to the next.
 * Drawing it any other way would paint risk onto road the driver has already
 * covered.
 */
export function riskSegments(
  route: AnalysedRoute,
): FeatureCollection<LineString, CheckpointProperties> {
  const line = route.geometry
  if (line.length < 2 || route.checkpoints.length < 2) {
    return { type: 'FeatureCollection', features: [] }
  }

  const total = route.metrics.distance_miles || 1
  const features: Array<Feature<LineString, CheckpointProperties>> = []

  for (let i = 0; i < route.checkpoints.length - 1; i += 1) {
    const from = route.checkpoints[i]
    const to = route.checkpoints[i + 1]
    if (!from || !to) continue

    // Map mile markers onto the simplified polyline proportionally. The
    // geometry is a display simplification of the real route, so this is an
    // approximation for *drawing* only -- every number shown comes from the
    // backend's full-resolution analysis.
    const startIdx = Math.floor(
      (from.distance_from_origin_miles / total) * (line.length - 1),
    )
    const endIdx = Math.ceil(
      (to.distance_from_origin_miles / total) * (line.length - 1),
    )
    const slice = line.slice(
      Math.max(0, Math.min(startIdx, line.length - 2)),
      Math.max(2, Math.min(endIdx + 1, line.length)),
    )
    if (slice.length < 2) continue

    features.push({
      type: 'Feature',
      geometry: { type: 'LineString', coordinates: slice.map(toLngLat) },
      properties: {
        routeId: route.route_id,
        index: from.index,
        level: from.risk.level,
        mile: from.distance_from_origin_miles,
        eta: from.eta,
        isOrigin: from.is_origin,
        isDestination: from.is_destination,
      },
    })
  }

  return { type: 'FeatureCollection', features }
}

export function checkpointPoints(
  route: AnalysedRoute,
): FeatureCollection<Point, CheckpointProperties> {
  return {
    type: 'FeatureCollection',
    features: route.checkpoints.map((checkpoint: Checkpoint) => ({
      type: 'Feature',
      geometry: {
        type: 'Point',
        coordinates: [checkpoint.longitude, checkpoint.latitude],
      },
      properties: {
        routeId: route.route_id,
        index: checkpoint.index,
        level: checkpoint.risk.level,
        mile: checkpoint.distance_from_origin_miles,
        eta: checkpoint.eta,
        isOrigin: checkpoint.is_origin,
        isDestination: checkpoint.is_destination,
      },
    })),
  }
}

/** Bounding box `[west, south, east, north]` across every route. */
export function routesBounds(
  routes: AnalysedRoute[],
): [number, number, number, number] | null {
  let west = Infinity
  let south = Infinity
  let east = -Infinity
  let north = -Infinity

  for (const route of routes) {
    for (const [lat, lng] of route.geometry) {
      if (lng < west) west = lng
      if (lng > east) east = lng
      if (lat < south) south = lat
      if (lat > north) north = lat
    }
  }

  if (!Number.isFinite(west) || !Number.isFinite(south)) return null
  return [west, south, east, north]
}

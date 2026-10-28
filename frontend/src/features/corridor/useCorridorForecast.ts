import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, fetchCorridorForecast } from '@/api/client'
import type {
  AnalysedRoute,
  CorridorForecastResponse,
  RouteAnalysisResponse,
} from '@/api/types'

export type CorridorStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface CorridorState {
  status: CorridorStatus
  data: CorridorForecastResponse | null
  error: ApiError | null
  /** Re-issue the request after a failure. */
  retry: () => void
}

/** Routes kept per analysis; a user rarely flips between more than three. */
const CACHE_LIMIT = 6

/**
 * What makes one corridor request distinct from another. The checkpoints are
 * fully determined by the analysis and the route, so the reference time,
 * load, route id and checkpoint count are enough -- and they are cheap to
 * compare on every render.
 */
export function corridorKey(
  analysis: RouteAnalysisResponse,
  route: AnalysedRoute,
): string {
  return [
    analysis.request.effective_departure_at,
    analysis.request.load_weight_lb,
    route.route_id,
    route.checkpoints.length,
  ].join('|')
}

/**
 * Loads the 0-48 h corridor frames for the selected route.
 *
 * One request per (analysis, route); results are cached in the hook so
 * switching back to a route already seen costs nothing. Changing the
 * selected hour never touches the network -- all 49 frames arrive at once,
 * which is what makes scrubbing and playback instant.
 *
 * Races: a route change aborts the in-flight request and marks its closure
 * stale, so a slow earlier response can never land on a newer selection.
 */
export function useCorridorForecast(
  analysis: RouteAnalysisResponse | null,
  route: AnalysedRoute | null,
): CorridorState {
  const [status, setStatus] = useState<CorridorStatus>('idle')
  const [data, setData] = useState<CorridorForecastResponse | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [attempt, setAttempt] = useState(0)

  const cache = useRef(new Map<string, CorridorForecastResponse>())
  const key = analysis && route ? corridorKey(analysis, route) : null

  useEffect(() => {
    if (!analysis || !route || !key) {
      // oxlint-disable-next-line react/set-state-in-effect
      setStatus('idle')
      setData(null)
      setError(null)
      return
    }

    const cached = cache.current.get(key)
    if (cached) {
      // oxlint-disable-next-line react/set-state-in-effect
      setStatus('ready')
      setData(cached)
      setError(null)
      return
    }

    const controller = new AbortController()
    let stale = false

    // oxlint-disable-next-line react/set-state-in-effect
    setStatus('loading')
    setData(null)
    setError(null)

    fetchCorridorForecast(
      {
        reference_at: analysis.request.effective_departure_at,
        load_weight_lb: analysis.request.load_weight_lb,
        route_id: route.route_id,
        timezone: analysis.request.departure_timezone,
        checkpoints: route.checkpoints.map((point) => ({
          index: point.index,
          latitude: point.latitude,
          longitude: point.longitude,
          distance_from_origin_miles: point.distance_from_origin_miles,
        })),
      },
      { signal: controller.signal },
    )
      .then((response) => {
        if (stale) return
        if (cache.current.size >= CACHE_LIMIT) {
          const oldest = cache.current.keys().next().value
          if (oldest !== undefined) cache.current.delete(oldest)
        }
        cache.current.set(key, response)
        setData(response)
        setStatus('ready')
      })
      .catch((caught: unknown) => {
        if (stale || controller.signal.aborted) return
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError({
                code: 'NETWORK_ERROR',
                message: 'Could not load the corridor forecast.',
                status: 0,
              }),
        )
        setStatus('error')
      })

    return () => {
      stale = true
      controller.abort()
    }
    // `key` stands in for the analysis/route fields that matter; `attempt`
    // forces a refetch after `retry()`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  return { status, data, error, retry }
}

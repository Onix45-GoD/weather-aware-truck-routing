import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import type { CorridorForecastRequest } from '@/api/types'
import { makeAnalysis, makeRoute, makeRoutes } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { corridorKey, useCorridorForecast } from './useCorridorForecast'

const fetchCorridorForecast = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, fetchCorridorForecast }
})

beforeEach(() => {
  fetchCorridorForecast.mockReset()
})

describe('useCorridorForecast', () => {
  it('is idle without an analysis or route', () => {
    const { result } = renderHook(() => useCorridorForecast(null, null))
    expect(result.current.status).toBe('idle')
    expect(fetchCorridorForecast).not.toHaveBeenCalled()
  })

  it('sends the analysis reference time, load and the route checkpoints', async () => {
    const analysis = makeAnalysis()
    const route = analysis.routes[0]!
    fetchCorridorForecast.mockResolvedValue(makeCorridorForecast(route))

    const { result } = renderHook(() => useCorridorForecast(analysis, route))
    expect(result.current.status).toBe('loading')
    await waitFor(() => expect(result.current.status).toBe('ready'))

    const [payload] = fetchCorridorForecast.mock.calls[0] as [CorridorForecastRequest]
    expect(payload.reference_at).toBe(analysis.request.effective_departure_at)
    expect(payload.load_weight_lb).toBe(analysis.request.load_weight_lb)
    expect(payload.route_id).toBe(route.route_id)
    expect(payload.timezone).toBe('America/Denver')
    expect(payload.checkpoints).toHaveLength(route.checkpoints.length)
    expect(payload.checkpoints[0]).toEqual({
      index: route.checkpoints[0]!.index,
      latitude: route.checkpoints[0]!.latitude,
      longitude: route.checkpoints[0]!.longitude,
      distance_from_origin_miles: route.checkpoints[0]!.distance_from_origin_miles,
    })
    // No geometry is resent.
    expect(JSON.stringify(payload)).not.toContain('geometry')
    expect(result.current.data?.frames).toHaveLength(49)
  })

  it('reuses a cached result when switching back to a route', async () => {
    const routes = makeRoutes(2)
    const analysis = makeAnalysis({ routes })
    fetchCorridorForecast.mockImplementation(async (payload: CorridorForecastRequest) =>
      makeCorridorForecast(routes.find((r) => r.route_id === payload.route_id)!),
    )

    const { result, rerender } = renderHook(
      ({ route }) => useCorridorForecast(analysis, route),
      { initialProps: { route: routes[0]! } },
    )
    await waitFor(() => expect(result.current.status).toBe('ready'))
    rerender({ route: routes[1]! })
    await waitFor(() => expect(result.current.data?.route_id).toBe(routes[1]!.route_id))
    rerender({ route: routes[0]! })
    await waitFor(() => expect(result.current.data?.route_id).toBe(routes[0]!.route_id))

    expect(fetchCorridorForecast).toHaveBeenCalledTimes(2)
  })

  it('aborts a superseded request and ignores its late response', async () => {
    const routes = makeRoutes(2)
    const analysis = makeAnalysis({ routes })
    let resolveFirst: (value: unknown) => void = () => {}
    fetchCorridorForecast
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(makeCorridorForecast(routes[1]!))

    const { result, rerender } = renderHook(
      ({ route }) => useCorridorForecast(analysis, route),
      { initialProps: { route: routes[0]! } },
    )
    const [, options] = fetchCorridorForecast.mock.calls[0] as [unknown, { signal: AbortSignal }]
    rerender({ route: routes[1]! })
    expect(options.signal.aborted).toBe(true)

    await waitFor(() => expect(result.current.data?.route_id).toBe(routes[1]!.route_id))
    resolveFirst(makeCorridorForecast(routes[0]!))
    await new Promise((r) => setTimeout(r, 0))
    expect(result.current.data?.route_id).toBe(routes[1]!.route_id)
  })

  it('surfaces failures and can retry', async () => {
    const analysis = makeAnalysis()
    const route = analysis.routes[0]!
    fetchCorridorForecast
      .mockRejectedValueOnce(new ApiError({ code: 'PROVIDER_TIMEOUT', message: 'slow', status: 504 }))
      .mockResolvedValueOnce(makeCorridorForecast(route))

    const { result } = renderHook(() => useCorridorForecast(analysis, route))
    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.message).toBe('slow')

    result.current.retry()
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(fetchCorridorForecast).toHaveBeenCalledTimes(2)
  })

  it('does not refetch for a new object describing the same route', async () => {
    const analysis = makeAnalysis()
    fetchCorridorForecast.mockResolvedValue(makeCorridorForecast(analysis.routes[0]!))
    const { result, rerender } = renderHook(
      ({ route }) => useCorridorForecast(analysis, route),
      { initialProps: { route: analysis.routes[0]! } },
    )
    await waitFor(() => expect(result.current.status).toBe('ready'))
    rerender({ route: { ...analysis.routes[0]! } })
    expect(fetchCorridorForecast).toHaveBeenCalledTimes(1)
  })

  it('changes key when the departure or load changes', () => {
    const analysis = makeAnalysis()
    const route = makeRoute()
    const later = makeAnalysis({
      request: { ...analysis.request, effective_departure_at: '2026-11-03T13:00:00+00:00' },
    })
    expect(corridorKey(analysis, route)).not.toBe(corridorKey(later, route))
  })
})

import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { makeAnalysis } from '@/test/fixtures'
import type { RouteAnalysisRequest } from '@/api/types'

import { useRouteAnalysis } from './useRouteAnalysis'

const analyseRoute = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, analyseRoute }
})

const PAYLOAD: RouteAnalysisRequest = {
  origin: 'Denver, CO',
  destination: 'Chicago, IL',
  departure_at: '2026-11-02T06:00',
  departure_timezone: 'America/Denver',
  load_weight_lb: 40_000,
  checkpoint_interval_miles: 25,
}

beforeEach(() => {
  analyseRoute.mockReset()
})

describe('useRouteAnalysis', () => {
  it('starts idle', () => {
    const { result } = renderHook(() => useRouteAnalysis())
    expect(result.current.status).toBe('idle')
    expect(result.current.data).toBeNull()
  })

  it('stores a successful analysis', async () => {
    const analysis = makeAnalysis()
    analyseRoute.mockResolvedValue(analysis)

    const { result } = renderHook(() => useRouteAnalysis())
    await act(async () => {
      await result.current.analyse(PAYLOAD)
    })

    expect(result.current.status).toBe('success')
    expect(result.current.data).toEqual(analysis)
  })

  it('captures field errors from a validation failure', async () => {
    analyseRoute.mockRejectedValue(
      new ApiError({
        code: 'INVALID_REQUEST',
        message: 'Invalid.',
        status: 400,
        fieldErrors: { origin: ['Too vague.'] },
      }),
    )

    const { result } = renderHook(() => useRouteAnalysis())
    await act(async () => {
      await result.current.analyse(PAYLOAD)
    })

    expect(result.current.status).toBe('error')
    expect(result.current.fieldErrors).toEqual({ origin: ['Too vague.'] })
  })

  it('keeps the previous result visible while reloading', async () => {
    const first = makeAnalysis()
    analyseRoute.mockResolvedValue(first)

    const { result } = renderHook(() => useRouteAnalysis())
    await act(async () => {
      await result.current.analyse(PAYLOAD)
    })

    let release: (value: unknown) => void = () => {}
    analyseRoute.mockImplementation(
      () => new Promise((resolve) => (release = resolve)),
    )

    act(() => {
      void result.current.analyse(PAYLOAD)
    })

    await waitFor(() => expect(result.current.isLoading).toBe(true))
    // The dashboard must not flash empty between analyses.
    expect(result.current.data).toEqual(first)

    await act(async () => {
      release(makeAnalysis())
    })
  })

  it('ignores a slow earlier response once a newer one is running', async () => {
    const stale = makeAnalysis({ recommendation_reason: 'STALE' })
    const fresh = makeAnalysis({ recommendation_reason: 'FRESH' })

    let releaseStale: (value: unknown) => void = () => {}
    analyseRoute
      .mockImplementationOnce(
        () => new Promise((resolve) => (releaseStale = resolve)),
      )
      .mockResolvedValueOnce(fresh)

    const { result } = renderHook(() => useRouteAnalysis())

    act(() => {
      void result.current.analyse(PAYLOAD)
    })
    await act(async () => {
      await result.current.analyse(PAYLOAD)
    })

    expect(result.current.data?.recommendation_reason).toBe('FRESH')

    // The first request now finishes. It must not overwrite the newer result.
    await act(async () => {
      releaseStale(stale)
    })

    expect(result.current.data?.recommendation_reason).toBe('FRESH')
  })

  it('aborts an in-flight request when a new one starts', async () => {
    analyseRoute.mockImplementation(() => new Promise(() => {}))

    const { result } = renderHook(() => useRouteAnalysis())
    act(() => {
      void result.current.analyse(PAYLOAD)
    })
    act(() => {
      void result.current.analyse(PAYLOAD)
    })

    const firstSignal = analyseRoute.mock.calls[0]?.[1]?.signal as AbortSignal
    await waitFor(() => expect(firstSignal.aborted).toBe(true))
  })

  it('resets back to idle', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis())
    const { result } = renderHook(() => useRouteAnalysis())

    await act(async () => {
      await result.current.analyse(PAYLOAD)
    })
    act(() => {
      result.current.reset()
    })

    expect(result.current.status).toBe('idle')
    expect(result.current.data).toBeNull()
  })

  it('aborts on unmount rather than setting state afterwards', async () => {
    analyseRoute.mockImplementation(() => new Promise(() => {}))

    const { result, unmount } = renderHook(() => useRouteAnalysis())
    act(() => {
      void result.current.analyse(PAYLOAD)
    })

    const signal = analyseRoute.mock.calls[0]?.[1]?.signal as AbortSignal
    unmount()

    await waitFor(() => expect(signal.aborted).toBe(true))
  })
})

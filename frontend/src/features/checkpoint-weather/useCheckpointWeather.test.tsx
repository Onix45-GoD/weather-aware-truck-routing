import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { makeCheckpoint } from '@/test/fixtures'
import { makeCheckpointWeather } from '@/test/weatherFixtures'

import { useCheckpointWeather } from './useCheckpointWeather'

const fetchCheckpointWeather = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, fetchCheckpointWeather }
})

beforeEach(() => {
  fetchCheckpointWeather.mockReset()
})

describe('useCheckpointWeather', () => {
  it('does nothing without a checkpoint', () => {
    const { result } = renderHook(() => useCheckpointWeather(null, true))
    expect(result.current.status).toBe('idle')
    expect(fetchCheckpointWeather).not.toHaveBeenCalled()
  })

  it('does nothing when the feature is off, even with a checkpoint', () => {
    const { result } = renderHook(() =>
      useCheckpointWeather(makeCheckpoint({ index: 3 }), false),
    )
    expect(result.current.status).toBe('idle')
    expect(fetchCheckpointWeather).not.toHaveBeenCalled()
  })

  it('sends the checkpoint position and ETA, then reports ready', async () => {
    const checkpoint = makeCheckpoint({ index: 2 })
    fetchCheckpointWeather.mockResolvedValue(makeCheckpointWeather())

    const { result } = renderHook(() => useCheckpointWeather(checkpoint, true))
    expect(result.current.status).toBe('loading')

    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.data?.source).toBe('openweathermap')

    const [query] = fetchCheckpointWeather.mock.calls[0] as [
      { lat: number; lon: number; at: string },
    ]
    expect(query.lat).toBe(checkpoint.latitude)
    expect(query.lon).toBe(checkpoint.longitude)
    expect(query.at).toBe(checkpoint.eta)
  })

  it('treats a 503 as "switched off", not as a failure', async () => {
    fetchCheckpointWeather.mockRejectedValue(
      new ApiError({
        code: 'CHECKPOINT_WEATHER_NOT_CONFIGURED',
        message: 'no key',
        status: 503,
      }),
    )
    const { result } = renderHook(() =>
      useCheckpointWeather(makeCheckpoint({ index: 1 }), true),
    )
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
  })

  it('reports other failures with their message', async () => {
    fetchCheckpointWeather.mockRejectedValue(
      new ApiError({ code: 'PROVIDER_TIMEOUT', message: 'too slow', status: 504 }),
    )
    const { result } = renderHook(() =>
      useCheckpointWeather(makeCheckpoint({ index: 1 }), true),
    )
    await waitFor(() => expect(result.current.status).toBe('error'))
    expect(result.current.error?.message).toBe('too slow')
  })

  it('aborts a superseded request and never applies its late result', async () => {
    const first = makeCheckpoint({ index: 1 })
    const second = makeCheckpoint({ index: 2 })

    let resolveFirst: (value: unknown) => void = () => {}
    fetchCheckpointWeather
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(makeCheckpointWeather({ place_name: 'Second' }))

    const { result, rerender } = renderHook(
      ({ checkpoint }) => useCheckpointWeather(checkpoint, true),
      { initialProps: { checkpoint: first } },
    )
    const [, firstOptions] = fetchCheckpointWeather.mock.calls[0] as [
      unknown,
      { signal: AbortSignal },
    ]

    rerender({ checkpoint: second })
    expect(firstOptions.signal.aborted).toBe(true)

    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.data?.place_name).toBe('Second')

    // The first request finally answers: it must be ignored.
    resolveFirst(makeCheckpointWeather({ place_name: 'First' }))
    await new Promise((r) => setTimeout(r, 0))
    expect(result.current.data?.place_name).toBe('Second')
  })

  it('does not refetch for a new object describing the same checkpoint', async () => {
    fetchCheckpointWeather.mockResolvedValue(makeCheckpointWeather())
    const { result, rerender } = renderHook(
      ({ checkpoint }) => useCheckpointWeather(checkpoint, true),
      { initialProps: { checkpoint: makeCheckpoint({ index: 4 }) } },
    )
    await waitFor(() => expect(result.current.status).toBe('ready'))

    rerender({ checkpoint: makeCheckpoint({ index: 4 }) })
    expect(fetchCheckpointWeather).toHaveBeenCalledTimes(1)
  })
})

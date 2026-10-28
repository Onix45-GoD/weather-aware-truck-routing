import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'

import { useHealth } from './useHealth'

const fetchHealth = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, fetchHealth }
})

beforeEach(() => {
  fetchHealth.mockReset()
})

describe('useHealth', () => {
  it('reports weather overlays when the server has a key', async () => {
    fetchHealth.mockResolvedValue({
      status: 'ok',
      providers: { openweathermap_key_configured: true },
    })

    const { result } = renderHook(() => useHealth())
    expect(result.current.status).toBe('loading')
    expect(result.current.weatherOverlaysAvailable).toBe(false)

    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.weatherOverlaysAvailable).toBe(true)
  })

  it('offers nothing optional when the key is absent', async () => {
    fetchHealth.mockResolvedValue({
      status: 'ok',
      providers: { openweathermap_key_configured: false },
    })

    const { result } = renderHook(() => useHealth())
    await waitFor(() => expect(result.current.status).toBe('ready'))
    expect(result.current.weatherOverlaysAvailable).toBe(false)
  })

  it('treats an unreachable server as nothing optional, not as an error', async () => {
    fetchHealth.mockRejectedValue(
      new ApiError({ code: 'NETWORK_ERROR', message: 'down', status: 0 }),
    )

    const { result } = renderHook(() => useHealth())
    await waitFor(() => expect(result.current.status).toBe('unavailable'))
    expect(result.current.health).toBeNull()
    expect(result.current.weatherOverlaysAvailable).toBe(false)
  })

  it('aborts the probe on unmount', () => {
    fetchHealth.mockReturnValue(new Promise(() => {}))
    const { unmount } = renderHook(() => useHealth())

    const [{ signal }] = fetchHealth.mock.calls[0] as [{ signal: AbortSignal }]
    expect(signal.aborted).toBe(false)
    unmount()
    expect(signal.aborted).toBe(true)
  })
})

import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { makeRoute } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { nextAvailableHour, useForecastPlayback } from './useForecastPlayback'

const route = makeRoute()

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

function setup(frames = makeCorridorForecast(route).frames, start = 0) {
  let hour = start
  const setHour = vi.fn((next: number) => {
    hour = next
  })
  const view = renderHook(
    ({ h }) => useForecastPlayback(frames, h, setHour, { intervalMs: 100 }),
    { initialProps: { h: hour } },
  )
  const tick = (ms = 100) => {
    act(() => {
      vi.advanceTimersByTime(ms)
    })
    view.rerender({ h: hour })
  }
  return { ...view, setHour, tick, current: () => hour }
}

describe('nextAvailableHour', () => {
  it('skips hours the provider did not cover', () => {
    const frames = makeCorridorForecast(route, {
      3: { available: false },
      4: { available: false },
    }).frames
    expect(nextAvailableHour(frames, 2)).toBe(5)
  })

  it('returns null at the end', () => {
    const frames = makeCorridorForecast(route).frames
    expect(nextAvailableHour(frames, 48)).toBeNull()
  })
})

describe('useForecastPlayback', () => {
  it('starts paused and advances one available hour per tick when playing', () => {
    const { result, tick, current } = setup()
    expect(result.current.playing).toBe(false)

    act(() => result.current.play())
    expect(result.current.playing).toBe(true)

    tick()
    expect(current()).toBe(1)
    tick()
    expect(current()).toBe(2)
  })

  it('skips unavailable hours rather than inventing them', () => {
    const frames = makeCorridorForecast(route, {
      1: { available: false },
      2: { available: false },
    }).frames
    const { result, tick, current } = setup(frames)
    act(() => result.current.play())
    tick()
    expect(current()).toBe(3)
  })

  it('stops at the last available hour', () => {
    const frames = makeCorridorForecast(route, { 48: { available: false } }).frames
    const { result, tick, current } = setup(frames, 46)
    act(() => result.current.play())
    tick()
    expect(current()).toBe(47)
    tick()
    expect(result.current.playing).toBe(false)
    expect(current()).toBe(47)
  })

  it('pauses when the user moves the slider', () => {
    const { result, rerender, tick } = setup()
    act(() => result.current.play())
    tick()
    expect(result.current.playing).toBe(true)

    // A value the player did not set: the user dragged.
    rerender({ h: 30 })
    expect(result.current.playing).toBe(false)
  })

  it('reset returns to +0 and stops', () => {
    const { result, setHour, tick } = setup()
    act(() => result.current.play())
    tick()
    act(() => result.current.reset())
    expect(result.current.playing).toBe(false)
    expect(setHour).toHaveBeenLastCalledWith(0)
  })

  it('pressing play at the end restarts from the first available hour', () => {
    const frames = makeCorridorForecast(route, { 0: { available: false } }).frames
    const { result, setHour, rerender, current } = setup(frames, 48)
    act(() => result.current.play())
    // The parent re-renders with the hour the player set, as App does.
    rerender({ h: current() })
    expect(setHour).toHaveBeenLastCalledWith(1)
    expect(result.current.playing).toBe(true)
  })

  it('clears its timer on unmount', () => {
    const { result, unmount, setHour } = setup()
    act(() => result.current.play())
    unmount()
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(setHour).not.toHaveBeenCalled()
  })

  it('never fetches: it only steps through frames already in memory', () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { result, tick } = setup()
    act(() => result.current.play())
    tick()
    tick()
    expect(fetchSpy).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })
})

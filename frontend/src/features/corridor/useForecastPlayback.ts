import { useCallback, useEffect, useRef, useState } from 'react'

import type { CorridorFrame } from '@/api/types'

export interface PlaybackOptions {
  /** Milliseconds per step. Slowed automatically under reduced motion. */
  intervalMs?: number | undefined
}

export interface Playback {
  playing: boolean
  play: () => void
  pause: () => void
  toggle: () => void
  /** Back to +0 and stop. */
  reset: () => void
  /** True under `prefers-reduced-motion`; playback steps more slowly. */
  reducedMotion: boolean
}

const DEFAULT_INTERVAL_MS = 700
const REDUCED_MOTION_INTERVAL_MS = 1600

function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return false
  }
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** The next hour after `current` that has a forecast, or null at the end. */
export function nextAvailableHour(
  frames: readonly CorridorFrame[],
  current: number,
): number | null {
  for (const frame of frames) {
    if (frame.hour > current && frame.available) return frame.hour
  }
  return null
}

/**
 * Steps the selected hour through the frames that exist.
 *
 * Playback is a timer over data already in memory: it never fetches, never
 * interpolates, and skips hours the provider did not cover rather than
 * inventing them. It stops at the last available hour. Any manual change
 * to the hour pauses it, so the slider never fights the user.
 */
export function useForecastPlayback(
  frames: readonly CorridorFrame[] | null,
  hour: number,
  setHour: (hour: number) => void,
  options: PlaybackOptions = {},
): Playback {
  const [playing, setPlaying] = useState(false)
  const reducedMotion = prefersReducedMotion()
  const intervalMs =
    options.intervalMs ??
    (reducedMotion ? REDUCED_MOTION_INTERVAL_MS : DEFAULT_INTERVAL_MS)

  // The hour the *player* last set, and the hour this hook last saw. A new
  // hour that the player did not set means the user moved the slider, which
  // pauses playback. An unchanged hour is never a user action -- it is just
  // a re-render that has not caught up with the player's own setHour yet.
  const lastSetByPlayer = useRef<number | null>(null)
  const previousHour = useRef(hour)

  useEffect(() => {
    const before = previousHour.current
    previousHour.current = hour
    if (!playing || hour === before) return
    if (lastSetByPlayer.current !== hour) {
      // oxlint-disable-next-line react/set-state-in-effect
      setPlaying(false)
      lastSetByPlayer.current = null
    }
  }, [hour, playing])

  useEffect(() => {
    if (!playing || !frames) return

    const timer = setInterval(() => {
      const next = nextAvailableHour(frames, hour)
      if (next === null) {
        setPlaying(false)
        lastSetByPlayer.current = null
        return
      }
      lastSetByPlayer.current = next
      setHour(next)
    }, intervalMs)

    return () => clearInterval(timer)
  }, [playing, frames, hour, setHour, intervalMs])

  const play = useCallback(() => {
    if (!frames) return
    // Pressing play at the end restarts from the first available frame.
    if (nextAvailableHour(frames, hour) === null) {
      const first = frames.find((frame) => frame.available)
      if (!first) return
      lastSetByPlayer.current = first.hour
      setHour(first.hour)
    } else {
      lastSetByPlayer.current = hour
    }
    setPlaying(true)
  }, [frames, hour, setHour])

  const pause = useCallback(() => {
    setPlaying(false)
    lastSetByPlayer.current = null
  }, [])

  const toggle = useCallback(() => {
    if (playing) pause()
    else play()
  }, [playing, play, pause])

  const reset = useCallback(() => {
    setPlaying(false)
    lastSetByPlayer.current = null
    setHour(0)
  }, [setHour])

  return { playing, play, pause, toggle, reset, reducedMotion }
}

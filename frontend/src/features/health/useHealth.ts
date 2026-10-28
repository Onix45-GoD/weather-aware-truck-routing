import { useEffect, useState } from 'react'

import { fetchHealth } from '@/api/client'
import type { HealthResponse } from '@/api/types'

export type HealthStatus = 'loading' | 'ready' | 'unavailable'

export interface HealthState {
  health: HealthResponse | null
  status: HealthStatus
  /** True when the server holds an OpenWeatherMap key for map overlays. */
  weatherOverlaysAvailable: boolean
}

/**
 * One health probe on mount. It tells the UI which optional, key-gated
 * features the server actually has, so a control is never offered for
 * something that would 503.
 *
 * Failure is not an error state worth showing: a missing backend surfaces
 * properly the moment the user analyses a trip. Here it just means "assume
 * nothing optional is available".
 */
export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthResponse | null>(null)
  const [status, setStatus] = useState<HealthStatus>('loading')

  useEffect(() => {
    const controller = new AbortController()

    fetchHealth({ signal: controller.signal })
      .then((response) => {
        setHealth(response)
        setStatus('ready')
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus('unavailable')
      })

    return () => controller.abort()
  }, [])

  return {
    health,
    status,
    weatherOverlaysAvailable:
      health?.providers['openweathermap_key_configured'] === true,
  }
}

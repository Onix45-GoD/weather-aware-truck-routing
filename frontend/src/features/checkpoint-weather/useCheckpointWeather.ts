import { useEffect, useState } from 'react'

import { ApiError, fetchCheckpointWeather } from '@/api/client'
import type { Checkpoint, CheckpointWeatherResponse } from '@/api/types'

export type CheckpointWeatherStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'unavailable'
  | 'error'

export interface CheckpointWeatherState {
  status: CheckpointWeatherStatus
  data: CheckpointWeatherResponse | null
  error: ApiError | null
}

const IDLE: CheckpointWeatherState = { status: 'idle', data: null, error: null }

/**
 * Loads the detailed weather for the selected checkpoint.
 *
 * One request per selection. A fast click through several checkpoints
 * aborts each superseded request, and a late response for an old
 * checkpoint can never land on a new one: the effect's cleanup both aborts
 * the fetch and marks the closure stale.
 *
 * `enabled` is the health flag -- when the server has no key, nothing is
 * requested and the panel explains instead of showing an error.
 */
export function useCheckpointWeather(
  checkpoint: Checkpoint | null,
  enabled: boolean,
): CheckpointWeatherState {
  const [state, setState] = useState<CheckpointWeatherState>(IDLE)

  // The identity that matters: a new checkpoint object with the same
  // location and ETA is the same lookup, and must not refetch.
  const key = checkpoint
    ? `${checkpoint.latitude},${checkpoint.longitude},${checkpoint.eta}`
    : null

  useEffect(() => {
    if (!checkpoint || !enabled || !key) {
      // oxlint-disable-next-line react/set-state-in-effect
      setState(IDLE)
      return
    }

    const controller = new AbortController()
    let stale = false

    // oxlint-disable-next-line react/set-state-in-effect
    setState({ status: 'loading', data: null, error: null })

    fetchCheckpointWeather(
      {
        lat: checkpoint.latitude,
        lon: checkpoint.longitude,
        at: checkpoint.eta,
      },
      { signal: controller.signal },
    )
      .then((data) => {
        if (!stale) setState({ status: 'ready', data, error: null })
      })
      .catch((error: unknown) => {
        if (stale || controller.signal.aborted) return
        const apiError =
          error instanceof ApiError
            ? error
            : new ApiError({
                code: 'NETWORK_ERROR',
                message: 'Could not load the weather for this checkpoint.',
                status: 0,
              })
        setState({
          status: apiError.status === 503 ? 'unavailable' : 'error',
          data: null,
          error: apiError,
        })
      })

    return () => {
      stale = true
      controller.abort()
    }
    // `key` stands in for the checkpoint fields that matter; `checkpoint`
    // itself changes identity on every analysis render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled])

  return state
}

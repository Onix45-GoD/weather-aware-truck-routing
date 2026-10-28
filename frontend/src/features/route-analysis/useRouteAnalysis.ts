import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError, analyseRoute } from '@/api/client'
import type { RouteAnalysisRequest, RouteAnalysisResponse } from '@/api/types'

export type AnalysisStatus = 'idle' | 'loading' | 'success' | 'error'

export interface AnalysisState {
  status: AnalysisStatus
  data: RouteAnalysisResponse | null
  error: ApiError | null
  /** Per-field messages from a 400, keyed by request field name. */
  fieldErrors: Record<string, string[]>
}

const INITIAL: AnalysisState = {
  status: 'idle',
  data: null,
  error: null,
  fieldErrors: {},
}

/**
 * Owns the analysis request lifecycle.
 *
 * Two races matter here and both are handled:
 *
 * 1. **Duplicate submission.** A second submit while one is in flight aborts
 *    the first. The user wants the newest answer, and leaving both running
 *    doubles provider quota for a result that will be discarded.
 * 2. **Stale responses.** A slow earlier request must never overwrite a newer
 *    result. Each run takes a sequence number and only the newest one is
 *    allowed to write state — aborting alone is not enough, because a
 *    response can already be in flight when the abort fires.
 *
 * Also guards against setting state after unmount, which React 19 tolerates
 * but which hides real bugs in tests.
 */
export function useRouteAnalysis() {
  const [state, setState] = useState<AnalysisState>(INITIAL)

  const controllerRef = useRef<AbortController | null>(null)
  const latestRunRef = useRef(0)
  const mountedRef = useRef(true)

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      controllerRef.current?.abort()
    }
  }, [])

  const analyse = useCallback(async (payload: RouteAnalysisRequest) => {
    controllerRef.current?.abort()

    const controller = new AbortController()
    controllerRef.current = controller

    const runId = latestRunRef.current + 1
    latestRunRef.current = runId

    const isStale = () => runId !== latestRunRef.current || !mountedRef.current

    setState((previous) => ({
      // Keep the previous result visible while reloading, so the dashboard
      // does not flash empty on every re-analysis.
      ...previous,
      status: 'loading',
      error: null,
      fieldErrors: {},
    }))

    try {
      const data = await analyseRoute(payload, { signal: controller.signal })
      if (isStale()) return null
      setState({ status: 'success', data, error: null, fieldErrors: {} })
      return data
    } catch (error) {
      if (isStale()) return null

      if (error instanceof ApiError) {
        setState((previous) => ({
          ...previous,
          status: 'error',
          error,
          fieldErrors: error.fieldErrors,
        }))
        return null
      }

      // An abort raised by our own cancellation path is not a failure.
      if (error instanceof DOMException && error.name === 'AbortError') {
        return null
      }
      throw error
    }
  }, [])

  const reset = useCallback(() => {
    controllerRef.current?.abort()
    latestRunRef.current += 1
    setState(INITIAL)
  }, [])

  return {
    ...state,
    isLoading: state.status === 'loading',
    analyse,
    reset,
  }
}

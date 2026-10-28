/**
 * Typed client for the Django API.
 *
 * Only ever talks to our own backend. No provider credential is referenced
 * here, and none should be: `VITE_*` variables are compiled into the bundle
 * and are therefore public. TomTom and Open-Meteo are reached by the server.
 */

import type {
  ApiErrorBody,
  HealthResponse,
  RouteAnalysisRequest,
  RouteAnalysisResponse,
} from './types'

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

/** A real analysis against live providers takes a few seconds. */
const DEFAULT_TIMEOUT_MS = 45_000

export function apiBaseUrl(): string {
  const configured = import.meta.env['VITE_API_BASE_URL']
  return (typeof configured === 'string' && configured.trim()) || DEFAULT_BASE_URL
}

/**
 * A failure that carries enough structure for the UI to react usefully.
 *
 * The distinction that matters: `isValidation` means the user can fix it by
 * editing the form, while everything else is an infrastructure problem they
 * can only retry. A trip with no safe route is *neither* -- that arrives as a
 * successful response with `recommended_route_id: null`.
 */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly field: string | null
  readonly fieldErrors: Record<string, string[]>

  constructor(init: {
    code: string
    message: string
    status: number
    field?: string | null
    fieldErrors?: Record<string, string[]> | null
  }) {
    super(init.message)
    this.name = 'ApiError'
    this.code = init.code
    this.status = init.status
    this.field = init.field ?? null
    this.fieldErrors = init.fieldErrors ?? {}
  }

  /** True when the user can fix this by changing the form. */
  get isValidation(): boolean {
    return (
      this.code === 'INVALID_REQUEST' ||
      this.code === 'GEOCODING_NO_RESULTS' ||
      this.code === 'LOCATION_AMBIGUOUS'
    )
  }

  /** True when retrying later is reasonable. */
  get isRetryable(): boolean {
    return (
      this.code === 'PROVIDER_TIMEOUT' ||
      this.code === 'PROVIDER_RATE_LIMITED' ||
      this.code === 'PROVIDER_UNAVAILABLE' ||
      this.code === 'NETWORK_ERROR'
    )
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false
  const candidate = (value as { error?: unknown }).error
  return typeof candidate === 'object' && candidate !== null
}

async function parseFailure(response: Response): Promise<ApiError> {
  let body: unknown = null
  try {
    body = await response.json()
  } catch {
    // A non-JSON body means something upstream of the app answered -- a proxy,
    // a 502 page. Nothing useful to show the user beyond the status.
  }

  if (isErrorBody(body)) {
    const { code, message, field, details } = body.error
    return new ApiError({
      code,
      message,
      status: response.status,
      field,
      fieldErrors: details,
    })
  }

  return new ApiError({
    code: 'INTERNAL_ERROR',
    message: `The server returned an unexpected ${response.status} response.`,
    status: response.status,
  })
}

interface RequestOptions {
  /** Lets the caller abandon a request whose result is no longer wanted. */
  signal?: AbortSignal
  timeoutMs?: number
}

async function request<T>(
  path: string,
  init: RequestInit,
  options: RequestOptions = {},
): Promise<T> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  // Abort if either the caller cancels or the timeout fires.
  const onCallerAbort = () => controller.abort()
  options.signal?.addEventListener('abort', onCallerAbort)

  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    })

    if (!response.ok) throw await parseFailure(response)
    return (await response.json()) as T
  } catch (error) {
    if (error instanceof ApiError) throw error

    // A caller-initiated abort is not a failure to report -- the result was
    // simply no longer wanted. Re-throw so the caller can ignore it.
    if (options.signal?.aborted) throw error

    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError({
        code: 'PROVIDER_TIMEOUT',
        message: `The analysis took longer than ${Math.round(
          timeoutMs / 1000,
        )} seconds. The routing or weather provider may be slow right now.`,
        status: 504,
      })
    }

    throw new ApiError({
      code: 'NETWORK_ERROR',
      message:
        'Could not reach the analysis service. Check that the backend is ' +
        'running and that VITE_API_BASE_URL points at it.',
      status: 0,
    })
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', onCallerAbort)
  }
}

export function analyseRoute(
  payload: RouteAnalysisRequest,
  options: RequestOptions = {},
): Promise<RouteAnalysisResponse> {
  return request<RouteAnalysisResponse>(
    '/api/v1/route-analysis',
    { method: 'POST', body: JSON.stringify(payload) },
    options,
  )
}

export function fetchHealth(options: RequestOptions = {}): Promise<HealthResponse> {
  return request<HealthResponse>('/api/v1/health', { method: 'GET' }, {
    timeoutMs: 5_000,
    ...options,
  })
}

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { makeAnalysis } from '@/test/fixtures'

import { ApiError, analyseRoute, apiBaseUrl } from './client'
import type { RouteAnalysisRequest } from './types'

const PAYLOAD: RouteAnalysisRequest = {
  origin: 'Denver, CO',
  destination: 'Chicago, IL',
  departure_at: '2026-11-02T06:00',
  departure_timezone: 'America/Denver',
  load_weight_lb: 40_000,
  checkpoint_interval_miles: 25,
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiBaseUrl', () => {
  it('falls back to the local Django server', () => {
    expect(apiBaseUrl()).toMatch(/^https?:\/\//)
  })
})

describe('analyseRoute requests', () => {
  it('posts JSON to the route-analysis endpoint', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(makeAnalysis()))

    await analyseRoute(PAYLOAD)

    const [url, init] = vi.mocked(fetch).mock.calls[0]!
    expect(String(url)).toContain('/api/v1/route-analysis')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual(PAYLOAD)
  })

  it('never sends a provider credential', async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse(makeAnalysis()))

    await analyseRoute(PAYLOAD)

    // The browser talks only to our own API. TomTom and Open-Meteo are
    // reached by the server, so no key should appear anywhere in the call.
    const [url, init] = vi.mocked(fetch).mock.calls[0]!
    const everything = `${String(url)} ${String(init?.body)} ${JSON.stringify(init?.headers)}`
    expect(everything).not.toMatch(/api[_-]?key|tomtom|subscription-key/i)
  })

  it('returns the parsed analysis', async () => {
    const analysis = makeAnalysis()
    vi.mocked(fetch).mockResolvedValue(jsonResponse(analysis))

    await expect(analyseRoute(PAYLOAD)).resolves.toEqual(analysis)
  })
})

describe('analyseRoute error mapping', () => {
  it('reads the structured error envelope', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'LOCATION_AMBIGUOUS',
            message: 'Could not resolve confidently.',
            field: 'origin',
            details: null,
          },
        },
        400,
      ),
    )

    const error = await analyseRoute(PAYLOAD).catch((caught) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('LOCATION_AMBIGUOUS')
    expect(error.field).toBe('origin')
    expect(error.isValidation).toBe(true)
  })

  it('exposes per-field details from a validation failure', async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: 'INVALID_REQUEST',
            message: 'Invalid.',
            field: null,
            details: { load_weight_lb: ['Too large.'] },
          },
        },
        400,
      ),
    )

    const error = await analyseRoute(PAYLOAD).catch((caught) => caught)
    expect(error.fieldErrors).toEqual({ load_weight_lb: ['Too large.'] })
  })

  it.each([
    ['PROVIDER_TIMEOUT', 504, true],
    ['PROVIDER_RATE_LIMITED', 429, true],
    ['PROVIDER_UNAVAILABLE', 502, true],
    ['INTERNAL_ERROR', 500, false],
  ])('maps %s and marks retryability', async (code, status, retryable) => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(
        { error: { code, message: 'Upstream problem.', field: null, details: null } },
        status,
      ),
    )

    const error = await analyseRoute(PAYLOAD).catch((caught) => caught)
    expect(error.code).toBe(code)
    expect(error.status).toBe(status)
    expect(error.isRetryable).toBe(retryable)
  })

  it('survives a non-JSON error body', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response('<html>502 Bad Gateway</html>', { status: 502 }),
    )

    const error = await analyseRoute(PAYLOAD).catch((caught) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toContain('502')
  })

  it('reports an unreachable backend as a network error', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('Failed to fetch'))

    const error = await analyseRoute(PAYLOAD).catch((caught) => caught)
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.message).toMatch(/VITE_API_BASE_URL/)
  })

  it('turns an exhausted timeout into a typed timeout error', async () => {
    vi.mocked(fetch).mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        const signal = (init as RequestInit).signal
        signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })
    })

    const promise = analyseRoute(PAYLOAD, { timeoutMs: 5 })
    const error = await promise.catch((caught) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('PROVIDER_TIMEOUT')
  })
})

describe('cancellation', () => {
  it('propagates a caller abort rather than reporting a failure', async () => {
    const controller = new AbortController()
    vi.mocked(fetch).mockImplementation((_url, init) => {
      return new Promise((_resolve, reject) => {
        const signal = (init as RequestInit).signal
        signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })
    })

    const promise = analyseRoute(PAYLOAD, { signal: controller.signal })
    controller.abort()

    const error = await promise.catch((caught) => caught)
    // Not an ApiError: an abandoned request is not a failure to report.
    expect(error).toBeInstanceOf(DOMException)
  })
})

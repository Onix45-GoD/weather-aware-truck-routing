/**
 * Renders the dashboard against a REAL captured API response.
 *
 * The other tests use hand-built fixtures, which are shaped by our own
 * assumptions. This one replays an actual `POST /api/v1/route-analysis`
 * body (live TomTom + Open-Meteo, Denver -> Chicago) so any render-time crash
 * on real data shape -- a null the fixtures never had, a field the mockups
 * invented -- surfaces here with a stack trace instead of as a blank page.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { RouteAnalysisResponse } from '@/api/types'
import { Providers } from '@/app/Providers'

import App from './App'
import realResponse from './test/real-response.json'

const analyseRoute = vi.hoisted(() => vi.fn())
const fetchHealth = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, analyseRoute, fetchHealth }
})

const real = realResponse as unknown as RouteAnalysisResponse

let consoleErrors: unknown[][] = []

beforeEach(() => {
  consoleErrors = []
  vi.spyOn(console, 'error').mockImplementation((...args: unknown[]) => {
    consoleErrors.push(args)
  })
  analyseRoute.mockResolvedValue(real)
  fetchHealth.mockResolvedValue({ status: 'ok', providers: {} })
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('dashboard against a real API response', () => {
  it('the captured response has the shape we expect', () => {
    expect(real.routes.length).toBeGreaterThan(0)
    expect(real.routes[0]!.checkpoints.length).toBeGreaterThan(0)
    expect(real.routes[0]!.geometry.length).toBeGreaterThan(2)
  })

  it('renders every panel without a single console error', async () => {
    render(
      <Providers>
        <App />
      </Providers>,
    )
    await userEvent.setup().click(
      screen.getByRole('button', { name: /analyze routes/i }),
    )

    // Route cards
    await waitFor(() =>
      expect(
        screen.getByText(`Route alternatives (${real.routes.length})`),
      ).toBeVisible(),
    )

    // Summary, checkpoint table, details, weather profile
    expect(screen.getByText('Total distance')).toBeVisible()
    expect(screen.getByRole('table', { name: /checkpoints/i })).toBeVisible()
    expect(screen.getByText(/weather along route/i)).toBeVisible()

    // Map still mounted after data arrives
    expect(screen.getByTestId('map-container')).toHaveAttribute(
      'data-route-count',
      String(real.routes.length),
    )

    // Any React render error, key warning, or thrown-in-effect lands here.
    expect(consoleErrors).toEqual([])
  })

  it('shows weather readings, not blanks, for a real checkpoint', async () => {
    render(
      <Providers>
        <App />
      </Providers>,
    )
    await userEvent.setup().click(
      screen.getByRole('button', { name: /analyze routes/i }),
    )

    const table = await screen.findByRole('table', { name: /checkpoints/i })
    // The real response has readings; a row of em dashes would mean the
    // weather was dropped somewhere between API and table.
    const dashes = table.querySelectorAll('td')
    const dashCount = Array.from(dashes).filter(
      (cell) => cell.textContent === '—',
    ).length
    const recommended = real.routes.find((r) => r.is_recommended) ?? real.routes[0]!
    const withWeather = recommended.checkpoints.filter((c) => c.weather).length
    expect(withWeather).toBeGreaterThan(0)
    expect(dashCount).toBeLessThan(dashes.length)
  })
})

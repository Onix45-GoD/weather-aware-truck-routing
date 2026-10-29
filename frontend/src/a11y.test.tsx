/**
 * Automated accessibility audit (axe-core) over the dashboard's main states.
 *
 * Colour contrast is excluded here: jsdom has no layout or paint, so axe
 * cannot compute it reliably. Contrast is checked in a real browser by the
 * Lighthouse run recorded in the README.
 */

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { axe } from 'vitest-axe'
import * as matchers from 'vitest-axe/matchers'

import { Providers } from '@/app/Providers'
import { CheckpointPopup } from '@/components/map/CheckpointPopup'
import { RouteComparison } from '@/components/route/RouteComparison'
import { ForecastTimeline } from '@/features/corridor/ForecastTimeline'
import { checkpointSeries } from '@/features/corridor/series'
import { makeAnalysis, makeCheckpoint, makeRoute, makeRoutes } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import App from './App'

expect.extend(matchers)

const analyseRoute = vi.hoisted(() => vi.fn())
const fetchPlaceSuggestions = vi.hoisted(() => vi.fn())
const fetchCorridorForecast = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, analyseRoute, fetchPlaceSuggestions, fetchCorridorForecast }
})

const RULES = { rules: { 'color-contrast': { enabled: false } } }

beforeEach(() => {
  window.localStorage.clear()
  analyseRoute.mockReset()
  fetchPlaceSuggestions.mockResolvedValue({ query: '', suggestions: [] })
  const routes = makeRoutes(3)
  analyseRoute.mockResolvedValue(makeAnalysis({ routes }))
  fetchCorridorForecast.mockImplementation(async (payload: { route_id?: string }) =>
    makeCorridorForecast(routes.find((r) => r.route_id === payload.route_id)!, { 40: { available: false } }),
  )
})

describe('accessibility', () => {
  it('first visit: form, guide and empty panels', async () => {
    const { container } = render(
      <Providers>
        <App />
      </Providers>,
    )
    expect(await axe(container, RULES)).toHaveNoViolations()
  })

  it('after an analysis: map stub, timeline, comparison, detail, cards', async () => {
    const { container } = render(
      <Providers>
        <App />
      </Providers>,
    )
    await userEvent.setup().click(screen.getByRole('button', { name: /analyze routes/i }))
    await screen.findByRole('table', { name: /route comparison/i })
    await waitFor(() => expect(fetchCorridorForecast).toHaveBeenCalled())
    await screen.findByTestId('forecast-timestamp')
    expect(await axe(container, RULES)).toHaveNoViolations()
  }, 20_000)

  it('with a checkpoint selected: hourly table and detail', async () => {
    const { container } = render(
      <Providers>
        <App />
      </Providers>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /analyze routes/i }))
    const table = await screen.findByRole('table', { name: /checkpoints/i })
    await user.click(within(table).getAllByRole('button')[1]!)
    await screen.findByRole('table', { name: /hourly forecast at this checkpoint/i })
    expect(await axe(container, RULES)).toHaveNoViolations()
  }, 20_000)

  it('the map popup content', async () => {
    const route = makeRoute()
    const series = checkpointSeries(makeCorridorForecast(route).frames, 1)
    const { container } = render(
      <Providers>
        <CheckpointPopup
          checkpoint={makeCheckpoint({ index: 1 })}
          timeZone="America/Denver"
          series={series}
          hour={3}
          onHourChange={vi.fn()}
        />
      </Providers>,
    )
    expect(await axe(container, RULES)).toHaveNoViolations()
  })

  it('the forecast timeline, including its hour strip', async () => {
    const route = makeRoute()
    const { container } = render(
      <Providers>
        <ForecastTimeline
          corridor={{ status: 'ready', data: makeCorridorForecast(route), error: null, retry: vi.fn() }}
          hour={5}
          onHourChange={vi.fn()}
          playback={{ playing: false, play: vi.fn(), pause: vi.fn(), toggle: vi.fn(), reset: vi.fn(), reducedMotion: false }}
          timeZone="America/Denver"
          enabled
        />
      </Providers>,
    )
    expect(await axe(container, RULES)).toHaveNoViolations()
  })

  it('the route comparison table', async () => {
    const { container } = render(
      <Providers>
        <RouteComparison analysis={makeAnalysis({ routes: makeRoutes(3) })} selectedRouteId="tomtom-0" onSelect={vi.fn()} />
      </Providers>,
    )
    expect(await axe(container, RULES)).toHaveNoViolations()
  })
})

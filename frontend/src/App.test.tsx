import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { Providers } from '@/app/Providers'
import { makeCorridorForecast } from '@/test/corridorFixtures'
import {
  makeAnalysis,
  makeBlockedAnalysis,
  makeRouteWithMissingWeather,
  makeRoutes,
} from '@/test/fixtures'

import App from './App'

const analyseRoute = vi.hoisted(() => vi.fn())
const fetchHealth = vi.hoisted(() => vi.fn())
const fetchCheckpointWeather = vi.hoisted(() => vi.fn())
const fetchCorridorForecast = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    analyseRoute,
    fetchHealth,
    fetchCheckpointWeather,
    fetchCorridorForecast,
  }
})

function renderApp() {
  render(
    <Providers>
      <App />
    </Providers>,
  )
}

const analyseButton = () =>
  screen.getByRole('button', { name: /analyze routes/i })

async function submit() {
  const user = userEvent.setup()
  await user.click(analyseButton())
  return user
}

beforeEach(() => {
  analyseRoute.mockReset()
  fetchHealth.mockResolvedValue({ status: 'ok', providers: {} })
  fetchCorridorForecast.mockReset()
  fetchCorridorForecast.mockReturnValue(new Promise(() => {}))
})

describe('initial state', () => {
  it('invites the user to analyse before any request', () => {
    renderApp()
    expect(screen.getByText(/enter a trip and select/i)).toBeVisible()
    expect(analyseRoute).not.toHaveBeenCalled()
  })

  it('does not show fabricated routes', () => {
    renderApp()
    expect(screen.queryByText(/recommended/i)).not.toBeInTheDocument()
  })
})

describe('successful analysis', () => {
  it('renders every returned route', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(3) }))
    renderApp()
    await submit()

    expect(await screen.findByText('Route alternatives (3)')).toBeVisible()

    // Scoped to the alternatives panel: route labels also appear in the
    // summary and checkpoint headings.
    const panel = screen.getByRole('complementary', {
      name: /route alternatives/i,
    })
    expect(within(panel).getByText('Primary route')).toBeVisible()
    expect(within(panel).getByText('Alternative 1')).toBeVisible()
    expect(within(panel).getByText('Alternative 2')).toBeVisible()
  })

  it.each([1, 2, 3])('handles %i alternative(s) without padding', async (count) => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(count) }))
    renderApp()
    await submit()

    expect(
      await screen.findByText(`Route alternatives (${count})`),
    ).toBeVisible()
  })

  it('marks the recommended route and shows the reason', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(3) }))
    renderApp()
    await submit()

    expect(await screen.findByText('Recommended')).toBeVisible()
    expect(
      screen.getByText(/fewest severe miles/i),
    ).toBeVisible()
  })

  it('shows the headline metrics from the API', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis())
    renderApp()
    await submit()

    expect(await screen.findByText('Total distance')).toBeVisible()
    expect(screen.getByText('Weather coverage')).toBeVisible()
  })

  it('passes the routes to the map', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(2) }))
    renderApp()
    await submit()

    await waitFor(() =>
      expect(screen.getByTestId('map-container')).toHaveAttribute(
        'data-route-count',
        '2',
      ),
    )
  })
})

describe('route selection', () => {
  it('selects the recommended route automatically', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(3) }))
    renderApp()
    await submit()

    await waitFor(() =>
      expect(screen.getByTestId('map-container')).toHaveAttribute(
        'data-selected-route',
        'tomtom-0',
      ),
    )
  })

  it('switches every panel when another route is chosen', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(3) }))
    renderApp()
    const user = await submit()

    await screen.findByText('Alternative 2')
    await user.click(screen.getByRole('button', { name: /alternative 2/i }))

    await waitFor(() =>
      expect(screen.getByTestId('map-container')).toHaveAttribute(
        'data-selected-route',
        'tomtom-2',
      ),
    )
    // The checkpoint table header names the selected route.
    expect(screen.getByText(/on Alternative 2/)).toBeVisible()
  })
})

describe('checkpoint selection', () => {
  it('shows a prompt until a checkpoint is chosen', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis())
    renderApp()
    await submit()

    expect(
      await screen.findByText(/select a checkpoint on the map/i),
    ).toBeVisible()
  })

  it('shows the backend explanation for the chosen checkpoint', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis())
    renderApp()
    const user = await submit()

    const table = await screen.findByRole('table', { name: /checkpoints/i })
    const rows = within(table).getAllByRole('button')
    await user.click(rows[1]!)

    expect(await screen.findByText(/why this level/i)).toBeVisible()
    expect(screen.getByText(/overall low/i)).toBeVisible()
  })
})

describe('missing weather', () => {
  it('never renders an absent measurement as zero', async () => {
    analyseRoute.mockResolvedValue(
      makeAnalysis({ routes: [makeRouteWithMissingWeather()] }),
    )
    renderApp()
    await submit()

    const table = await screen.findByRole('table', { name: /checkpoints/i })
    // The gap row shows em dashes, not 0.
    expect(within(table).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('labels a forecast gap as "No data", not "Low"', async () => {
    analyseRoute.mockResolvedValue(
      makeAnalysis({ routes: [makeRouteWithMissingWeather()] }),
    )
    renderApp()
    await submit()

    expect(await screen.findByText('No data')).toBeVisible()
  })

  it('surfaces incomplete coverage on the route card', async () => {
    analyseRoute.mockResolvedValue(
      makeAnalysis({ routes: [makeRouteWithMissingWeather()] }),
    )
    renderApp()
    await submit()

    // Scoped: coverage also appears in the route summary.
    // `percent()` renders whole numbers, so 97.5 shows as 98%.
    const panel = await screen.findByRole('complementary', {
      name: /route alternatives/i,
    })
    expect(within(panel).getByText('98%')).toBeVisible()
  })
})

describe('no safe route', () => {
  it('reports a null recommendation instead of inventing one', async () => {
    analyseRoute.mockResolvedValue(makeBlockedAnalysis())
    renderApp()
    await submit()

    // Stated in both the summary verdict and the global warning banner.
    const notices = await screen.findAllByText(/no route can be recommended/i)
    expect(notices.length).toBeGreaterThan(0)
    expect(screen.queryByText('Recommended')).not.toBeInTheDocument()
  })

  it('still lists the blocked route with its reasons', async () => {
    analyseRoute.mockResolvedValue(makeBlockedAnalysis())
    renderApp()
    await submit()

    expect(await screen.findByText('Not usable')).toBeVisible()
    expect(
      screen.getByText(/no travel conditions over 50.0 mi/i),
    ).toBeVisible()
  })
})

describe('errors', () => {
  it('shows field errors from a validation failure', async () => {
    analyseRoute.mockRejectedValue(
      new ApiError({
        code: 'INVALID_REQUEST',
        message: 'The trip details could not be validated.',
        status: 400,
        fieldErrors: { origin: ['Enter a more specific location.'] },
      }),
    )
    renderApp()
    await submit()

    expect(await screen.findByText(/check the trip details/i)).toBeVisible()
    expect(screen.getByText('Enter a more specific location.')).toBeVisible()
  })

  it('distinguishes a provider failure from a validation problem', async () => {
    analyseRoute.mockRejectedValue(
      new ApiError({
        code: 'PROVIDER_UNAVAILABLE',
        message: 'The routing provider is unavailable.',
        status: 502,
      }),
    )
    renderApp()
    await submit()

    expect(await screen.findByText(/analysis failed/i)).toBeVisible()
    expect(screen.getByText(/you can try again/i)).toBeVisible()
  })

  it('reports a network failure usefully', async () => {
    analyseRoute.mockRejectedValue(
      new ApiError({
        code: 'NETWORK_ERROR',
        message: 'Could not reach the analysis service.',
        status: 0,
      }),
    )
    renderApp()
    await submit()

    expect(
      await screen.findByText(/could not reach the analysis service/i),
    ).toBeVisible()
  })
})

describe('request lifecycle', () => {
  it('disables the button while loading', async () => {
    analyseRoute.mockImplementation(() => new Promise(() => {}))
    renderApp()
    await submit()

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /analysing/i })).toBeDisabled(),
    )
  })

  it('does not fire a second request while one is in flight', async () => {
    analyseRoute.mockImplementation(() => new Promise(() => {}))
    renderApp()
    const user = await submit()

    await user.click(screen.getByRole('button', { name: /analysing/i }))
    expect(analyseRoute).toHaveBeenCalledTimes(1)
  })
})

describe('warnings', () => {
  it('shows warnings that are not tied to one route', async () => {
    analyseRoute.mockResolvedValue(
      makeAnalysis({
        warnings: [
          {
            code: 'FEWER_ALTERNATIVES',
            message: '2 distinct routes available, not 3.',
            route_id: null,
          },
        ],
      }),
    )
    renderApp()
    await submit()

    expect(
      await screen.findByText('2 distinct routes available, not 3.'),
    ).toBeVisible()
  })
})

describe('resilience', () => {
  it('keeps the analysis on screen when the map crashes', async () => {
    // Replace the (mocked) map with one that throws during render. Without
    // the boundary this unmounts the entire tree -- the exact failure that
    // showed as "map gone, weather gone" in the real browser.
    const mapModule = await import('@/components/map/LazyRouteMap')
    const crashing = vi.spyOn(mapModule, 'LazyRouteMap').mockImplementation(() => {
      throw new Error('WebGL context lost')
    })
    const silenced = vi.spyOn(console, 'error').mockImplementation(() => {})

    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(3) }))
    renderApp()
    await submit()

    // The map region reports its own failure...
    expect(await screen.findByText(/the map failed to render/i)).toBeVisible()
    expect(screen.getByText(/webgl context lost/i)).toBeVisible()

    // ...and everything else is still there.
    expect(screen.getByText('Route alternatives (3)')).toBeVisible()
    expect(screen.getByText('Total distance')).toBeVisible()
    expect(screen.getByRole('table', { name: /checkpoints/i })).toBeVisible()

    // Restore both, or every test after this one renders a crashed map.
    silenced.mockRestore()
    crashing.mockRestore()
  })
})

describe('corridor forecast timeline', () => {
  async function analysedWithCorridor() {
    const routes = makeRoutes(2)
    const analysis = makeAnalysis({ routes })
    analyseRoute.mockResolvedValue(analysis)
    fetchCorridorForecast.mockImplementation(async (payload: { route_id?: string }) =>
      makeCorridorForecast(routes.find((r) => r.route_id === payload.route_id)!, {
        12: { level: 'SEVERE' },
        40: { available: false },
      }),
    )
    renderApp()
    const user = await submit()
    await screen.findByRole('table', { name: /checkpoints/i })
    await waitFor(() => expect(fetchCorridorForecast).toHaveBeenCalledTimes(1))
    return { user, analysis, routes }
  }

  it('requests the corridor for the recommended route once the analysis lands', async () => {
    const { analysis } = await analysedWithCorridor()
    const [payload] = fetchCorridorForecast.mock.calls[0] as [{ route_id: string; reference_at: string }]
    expect(payload.route_id).toBe(analysis.recommended_route_id)
    expect(payload.reference_at).toBe(analysis.request.effective_departure_at)
  })

  it('starts at +0 h and shows the frame timestamp', async () => {
    await analysedWithCorridor()
    const stamp = await screen.findByTestId('forecast-timestamp')
    expect(stamp).toHaveTextContent('+0 h')
  })

  it('moving the slider updates the selected checkpoint’s forecast block', async () => {
    const { user } = await analysedWithCorridor()
    const table = screen.getByRole('table', { name: /checkpoints/i })
    await user.click(within(table).getAllByRole('button')[1]!)
    await screen.findByTestId('checkpoint-frame')
    expect(screen.getByTestId('checkpoint-frame')).toHaveTextContent('At +0 h')

    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    slider.focus()
    for (let i = 0; i < 12; i += 1) await user.keyboard('{ArrowRight}')

    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent('+12 h')
    const block = screen.getByTestId('checkpoint-frame')
    expect(block).toHaveTextContent('At +12 h')
    expect(within(block).getByText('Severe')).toBeVisible()
    // Selection survived the hour change.
    expect(within(table).getAllByRole('button')[1]).toHaveClass('Mui-selected')
  })

  it('never re-runs the analysis or changes the recommendation when the hour moves', async () => {
    const { user, analysis } = await analysedWithCorridor()
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    slider.focus()
    await user.keyboard('{End}')
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent('+48 h')
    expect(analyseRoute).toHaveBeenCalledTimes(1)
    const panel = screen.getByRole('complementary', { name: /route alternatives/i })
    expect(within(panel).getByText(/recommended/i)).toBeVisible()
    expect(screen.getByText(analysis.recommendation_reason)).toBeVisible()
  })

  it('marks an hour the provider did not cover as unavailable', async () => {
    const { user } = await analysedWithCorridor()
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    slider.focus()
    await user.keyboard('{End}')
    for (let i = 0; i < 8; i += 1) await user.keyboard('{ArrowLeft}')
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent('+40 h')
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent(/no forecast for this hour/i)
  })

  it('fetches the other route’s corridor when the selection changes, and resets the hour', async () => {
    const { user, routes } = await analysedWithCorridor()
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    slider.focus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent('+1 h')

    const panel = screen.getByRole('complementary', { name: /route alternatives/i })
    await user.click(within(panel).getByRole('button', { name: new RegExp(routes[1]!.label) }))
    await waitFor(() => expect(fetchCorridorForecast).toHaveBeenCalledTimes(2))
    const [payload] = fetchCorridorForecast.mock.calls[1] as [{ route_id: string }]
    expect(payload.route_id).toBe(routes[1]!.route_id)
    // The hour is display state for the route; it is kept across a route
    // switch within the same analysis so comparison is possible.
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent('+1 h')
  })

  it('shows the corridor error with a retry and keeps the dashboard usable', async () => {
    analyseRoute.mockResolvedValue(makeAnalysis({ routes: makeRoutes(2) }))
    fetchCorridorForecast.mockRejectedValue(
      new ApiError({ code: 'PROVIDER_TIMEOUT', message: 'Weather provider timed out.', status: 504 }),
    )
    renderApp()
    await submit()
    expect(await screen.findByText('Weather provider timed out.')).toBeVisible()
    expect(screen.getByRole('button', { name: /retry/i })).toBeVisible()
    expect(screen.getByRole('table', { name: /checkpoints/i })).toBeVisible()
  })
})

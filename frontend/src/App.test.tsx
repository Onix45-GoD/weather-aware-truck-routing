import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { Providers } from '@/app/Providers'
import {
  makeAnalysis,
  makeBlockedAnalysis,
  makeRouteWithMissingWeather,
  makeRoutes,
} from '@/test/fixtures'

import App from './App'

const analyseRoute = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, analyseRoute }
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
    vi.spyOn(mapModule, 'LazyRouteMap').mockImplementation(() => {
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

    silenced.mockRestore()
  })
})

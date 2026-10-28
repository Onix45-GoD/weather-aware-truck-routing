import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { Providers } from '@/app/Providers'
import { makeRoute } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { ForecastTimeline } from './ForecastTimeline'
import { frameLabel } from './frameLabel'
import type { CorridorState } from './useCorridorForecast'
import type { Playback } from './useForecastPlayback'

const route = makeRoute()

function playback(overrides: Partial<Playback> = {}): Playback {
  return {
    playing: false,
    play: vi.fn(),
    pause: vi.fn(),
    toggle: vi.fn(),
    reset: vi.fn(),
    reducedMotion: false,
    ...overrides,
  }
}

function ready(data = makeCorridorForecast(route)): CorridorState {
  return { status: 'ready', data, error: null, retry: vi.fn() }
}

function renderTimeline(
  corridor: CorridorState,
  props: Partial<React.ComponentProps<typeof ForecastTimeline>> = {},
) {
  const onHourChange = vi.fn()
  render(
    <Providers>
      <ForecastTimeline
        corridor={corridor}
        hour={0}
        onHourChange={onHourChange}
        playback={playback()}
        timeZone="America/Denver"
        enabled
        {...props}
      />
    </Providers>,
  )
  return { onHourChange }
}

describe('ForecastTimeline', () => {
  it('labels the slider and its hour marks', () => {
    renderTimeline(ready())
    const slider = screen.getByRole('slider', { name: /forecast hour after departure/i })
    expect(slider).toHaveAttribute('aria-valuemin', '0')
    expect(slider).toHaveAttribute('aria-valuemax', '48')
    for (const mark of ['+0 h', '+12 h', '+24 h', '+36 h', '+48 h']) {
      expect(screen.getAllByText(mark).length).toBeGreaterThan(0)
    }
  })

  it('shows the selected frame timestamp in the trip timezone', () => {
    renderTimeline(ready(), { hour: 12 })
    const stamp = screen.getByTestId('forecast-timestamp')
    // Frame 12 = 2026-11-03T01:00Z = Mon 2 Nov, 6:00 PM MST.
    expect(stamp).toHaveTextContent('+12 h')
    expect(stamp).toHaveTextContent(/6:00 PM/)
    expect(stamp).toHaveTextContent(/MST/)
  })

  it('says what the slider changes and what it does not', () => {
    renderTimeline(ready())
    expect(
      screen.getByText(/route, ETAs and recommendation do not change/i),
    ).toBeVisible()
  })

  it('reports the hour via keyboard', async () => {
    const { onHourChange } = renderTimeline(ready())
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    slider.focus()
    await userEvent.setup().keyboard('{ArrowRight}')
    expect(onHourChange).toHaveBeenCalledWith(1)
  })

  it('exposes the timestamp as the slider value text', () => {
    renderTimeline(ready(), { hour: 12 })
    const slider = screen.getByRole('slider', { name: /forecast hour/i })
    expect(slider.getAttribute('aria-valuetext')).toMatch(/12 hours after departure/)
    expect(slider.getAttribute('aria-valuetext')).toMatch(/6:00 PM/)
  })

  it('shows a loading state', () => {
    renderTimeline({ status: 'loading', data: null, error: null, retry: vi.fn() })
    expect(screen.getByLabelText(/loading corridor forecast/i)).toBeInTheDocument()
    expect(screen.getByRole('slider')).toBeDisabled()
  })

  it('shows the error and offers retry', async () => {
    const retry = vi.fn()
    renderTimeline({
      status: 'error',
      data: null,
      error: new ApiError({ code: 'PROVIDER_TIMEOUT', message: 'Weather provider timed out.', status: 504 }),
      retry,
    })
    expect(screen.getByText('Weather provider timed out.')).toBeVisible()
    await userEvent.setup().click(screen.getByRole('button', { name: /retry/i }))
    expect(retry).toHaveBeenCalled()
  })

  it('counts and marks unavailable hours', () => {
    const data = makeCorridorForecast(route, {
      40: { available: false },
      41: { available: false },
    })
    renderTimeline(ready(data), { hour: 40 })
    expect(screen.getByText(/2 of 49 hours unavailable/)).toBeVisible()
    expect(screen.getByTestId('forecast-timestamp')).toHaveTextContent(/no forecast for this hour/i)
    const strip = screen.getByRole('list', { name: /worst risk on the route by hour/i })
    const cells = within(strip).getAllByRole('listitem')
    expect(cells).toHaveLength(49)
    expect(cells[40]).toHaveAttribute('title', '+40 h: no forecast')
    expect(cells[40]).toHaveAttribute('aria-current', 'time')
  })

  it('colours the strip by each hour’s worst level', () => {
    const data = makeCorridorForecast(route, { 7: { level: 'SEVERE' } })
    renderTimeline(ready(data))
    const strip = screen.getByRole('list', { name: /worst risk/i })
    const cells = within(strip).getAllByRole('listitem')
    expect(cells[7]).toHaveAttribute('title', '+7 h: Severe')
    expect(cells[8]).toHaveAttribute('title', '+8 h: Low')
  })

  it('wires play, pause and reset', async () => {
    const pb = playback()
    renderTimeline(ready(), { playback: pb, hour: 5 })
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /play forecast/i }))
    expect(pb.toggle).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /reset to departure/i }))
    expect(pb.reset).toHaveBeenCalled()
  })

  it('shows pause while playing', () => {
    renderTimeline(ready(), { playback: playback({ playing: true }) })
    expect(screen.getByRole('button', { name: /pause playback/i })).toHaveAttribute('aria-pressed', 'true')
  })

  it('disables the controls before an analysis', () => {
    renderTimeline({ status: 'idle', data: null, error: null, retry: vi.fn() }, { enabled: false })
    expect(screen.getByRole('slider')).toBeDisabled()
    expect(screen.getByRole('button', { name: /play forecast/i })).toBeDisabled()
  })
})

describe('frameLabel', () => {
  it('renders the instant in the given zone with its abbreviation', () => {
    const frame = makeCorridorForecast(route).frames[0]!
    expect(frameLabel(frame.at, 'America/Denver')).toMatch(/6:00 AM MST/)
    expect(frameLabel(null, 'America/Denver')).toBe('—')
  })
})

import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { Providers } from '@/app/Providers'
import type { CheckpointWeatherState } from '@/features/checkpoint-weather/useCheckpointWeather'
import { ApiError } from '@/api/client'
import { makeCheckpoint } from '@/test/fixtures'
import { makeCheckpointWeather } from '@/test/weatherFixtures'

import { CheckpointConditions } from './CheckpointConditions'

function renderConditions(
  weather: CheckpointWeatherState,
  available = true,
) {
  return render(
    <Providers>
      <CheckpointConditions
        checkpoint={makeCheckpoint({ index: 2 })}
        weather={weather}
        available={available}
        timeZone="UTC"
      />
    </Providers>,
  )
}

const ready = (): CheckpointWeatherState => ({
  status: 'ready',
  data: makeCheckpointWeather(),
  error: null,
})

describe('CheckpointConditions', () => {
  it('explains when the server has no key instead of failing', () => {
    renderConditions({ status: 'idle', data: null, error: null }, false)
    expect(screen.getByText(/OPENWEATHERMAP_API_KEY/)).toBeVisible()
  })

  it('shows a loading state while fetching', () => {
    renderConditions({ status: 'loading', data: null, error: null })
    expect(screen.getByLabelText(/loading weather/i)).toBeInTheDocument()
  })

  it('separates now from at-ETA, both labelled', () => {
    renderConditions(ready())
    expect(screen.getByText(/^Now ·/)).toBeVisible()
    expect(screen.getByText(/^At ETA ·/)).toBeVisible()
    expect(screen.getByText('few clouds')).toBeVisible()
    expect(screen.getByText('light rain')).toBeVisible()
    expect(screen.getByText('72°')).toBeVisible() // 71.6 °F rounded
    expect(screen.getByText(/30% chance of precipitation/)).toBeVisible()
  })

  it('reports how far the nearest slot is from the ETA', () => {
    renderConditions(ready())
    expect(screen.getByText(/slot 50m after ETA/)).toBeVisible()
  })

  it('converts to Celsius on request', async () => {
    renderConditions(ready())
    await userEvent.setup().click(screen.getByRole('button', { name: /celsius/i }))
    expect(screen.getByText('22°')).toBeVisible() // 71.6 °F
    expect(screen.queryByText('72°')).not.toBeInTheDocument()
  })

  it('renders the observed stats', () => {
    renderConditions(ready())
    expect(screen.getByText('2 mph ESE')).toBeVisible()
    expect(screen.getByText('94%')).toBeVisible()
    expect(screen.getByText('6.2 mi')).toBeVisible()
    expect(screen.getByText('1021 hPa')).toBeVisible()
  })

  it('marks the ETA slot in the forecast strip', () => {
    renderConditions(ready())
    const strip = screen.getByRole('list', { name: /forecast around eta/i })
    const current = within(strip).getAllByRole('listitem').find(
      (item) => item.getAttribute('aria-current') === 'time',
    )
    expect(current).toBeDefined()
    expect(within(current!).getByText('30%')).toBeVisible()
  })

  it('says so when the ETA is beyond the forecast window', () => {
    renderConditions({
      status: 'ready',
      data: makeCheckpointWeather({ at_eta: null, eta_gap_minutes: null, eta_beyond_horizon: true }),
      error: null,
    })
    expect(screen.getByText(/beyond the 5-day forecast window/i)).toBeVisible()
  })

  it('shows the server message on failure', () => {
    renderConditions({
      status: 'error',
      data: null,
      error: new ApiError({ code: 'PROVIDER_TIMEOUT', message: 'Weather provider timed out.', status: 504 }),
    })
    expect(screen.getByText('Weather provider timed out.')).toBeVisible()
  })

  it('never claims to be the risk verdict', () => {
    renderConditions(ready())
    expect(screen.getByText(/unaffected by this panel/i)).toBeVisible()
  })
})

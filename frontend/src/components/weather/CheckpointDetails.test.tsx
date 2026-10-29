import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { checkpointSeries } from '@/features/corridor/series'
import { makeCheckpoint, makeRoute } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { CheckpointDetails } from './CheckpointDetails'

const route = makeRoute()
const checkpoint = makeCheckpoint({ index: 2 })
const series = checkpointSeries(
  makeCorridorForecast(route, { 12: { levels: { 2: 'HIGH' } }, 40: { available: false } }).frames,
  2,
)

function renderDetails(props: Partial<React.ComponentProps<typeof CheckpointDetails>> = {}) {
  const onHourChange = vi.fn()
  render(
    <Providers>
      <CheckpointDetails
        route={route}
        checkpoint={checkpoint}
        timeZone="America/Denver"
        series={series}
        hour={0}
        onHourChange={onHourChange}
        {...props}
      />
    </Providers>,
  )
  return { onHourChange }
}

describe('CheckpointDetails', () => {
  it('prompts until a checkpoint is chosen', () => {
    renderDetails({ checkpoint: null })
    expect(screen.getByText(/select a checkpoint on the map/i)).toBeVisible()
  })

  it('shows the ETA conditions, the level and the backend explanation', () => {
    renderDetails()
    expect(screen.getByText(/Checkpoint 2/)).toBeVisible()
    expect(screen.getByText(/Mile 50 · arrives/)).toBeVisible()
    expect(screen.getByText('18 mph')).toBeVisible()
    expect(screen.getByText('Gusts 26 mph')).toBeVisible()
    expect(screen.getByText(/why this level/i)).toBeVisible()
    expect(screen.getByText(checkpoint.risk.explanation)).toBeVisible()
  })

  it('lists all 49 hours at this checkpoint with the selected one marked', () => {
    renderDetails({ hour: 12 })
    const table = screen.getByRole('table', { name: /hourly forecast at this checkpoint/i })
    const rows = within(table).getAllByRole('button')
    expect(rows).toHaveLength(49)
    expect(rows[12]).toHaveAttribute('aria-current', 'time')
    expect(within(rows[12]!).getByText('High')).toBeVisible()
    expect(within(rows[11]!).getByText('Low')).toBeVisible()
  })

  it('renders an uncovered hour as dashes and No data, never as calm', () => {
    renderDetails()
    const table = screen.getByRole('table', { name: /hourly forecast/i })
    const row = within(table).getAllByRole('button')[40]!
    expect(within(row).getByText('No data')).toBeVisible()
    expect(within(row).getAllByText('—')).toHaveLength(3)
    expect(within(row).queryByText('Low')).not.toBeInTheDocument()
  })

  it('moves the timeline when a row is chosen, by mouse or keyboard', async () => {
    const { onHourChange } = renderDetails()
    const table = screen.getByRole('table', { name: /hourly forecast/i })
    const rows = within(table).getAllByRole('button')
    const user = userEvent.setup()
    await user.click(rows[7]!)
    expect(onHourChange).toHaveBeenCalledWith(7)
    rows[9]!.focus()
    await user.keyboard('{Enter}')
    expect(onHourChange).toHaveBeenCalledWith(9)
  })

  it('says it is loading before the series exists', () => {
    renderDetails({ series: null })
    expect(screen.getByText(/loading hourly forecast/i)).toBeVisible()
  })

  it('never renders an absent ETA measurement as zero', () => {
    renderDetails({
      checkpoint: makeCheckpoint({
        index: 2,
        weather: { wind_mph: null, wind_gust_mph: null, rain_in_hr: 0.1, snow_in_hr: null, forecast_time: null },
      }),
    })
    expect(screen.getAllByText('—').length).toBeGreaterThan(0)
    expect(screen.getByText('0.10 in/hr')).toBeVisible()
  })
})

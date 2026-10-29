import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { checkpointSeries } from '@/features/corridor/series'
import { makeCheckpoint, makeRoute } from '@/test/fixtures'
import { makeCorridorForecast } from '@/test/corridorFixtures'

import { CheckpointPopup } from './CheckpointPopup'

const route = makeRoute()
const checkpoint = makeCheckpoint({ index: 2 })

function renderPopup(hour = 0, series = checkpointSeries(makeCorridorForecast(route, { 5: { level: 'HIGH' }, 40: { available: false } }).frames, 2)) {
  const onHourChange = vi.fn()
  render(
    <Providers>
      <CheckpointPopup
        checkpoint={checkpoint}
        timeZone="America/Denver"
        series={series}
        hour={hour}
        onHourChange={onHourChange}
      />
    </Providers>,
  )
  return { onHourChange }
}

describe('CheckpointPopup', () => {
  it('shows the ETA conditions and risk at a glance', () => {
    renderPopup()
    const popup = screen.getByTestId('checkpoint-popup')
    expect(within(popup).getByText(/Checkpoint 2 · mile 50/)).toBeVisible()
    expect(within(popup).getByText(/^ETA/)).toBeVisible()
    expect(within(popup).getByText('18 mph')).toBeVisible()
    expect(within(popup).getAllByText('Low').length).toBeGreaterThan(0)
  })

  it('draws 49 clickable hour cells and reports the chosen hour', async () => {
    const { onHourChange } = renderPopup()
    const strip = screen.getByRole('list', { name: /risk by hour at this checkpoint/i })
    const cells = within(strip).getAllByRole('button')
    expect(cells).toHaveLength(49)
    expect(cells[5]).toHaveAccessibleName('+5 h: High')
    expect(cells[40]).toHaveAccessibleName('+40 h: no forecast')
    await userEvent.setup().click(cells[5]!)
    expect(onHourChange).toHaveBeenCalledWith(5)
  })

  it('marks the selected hour and shows its measurements', () => {
    renderPopup(5)
    const strip = screen.getByRole('list', { name: /risk by hour/i })
    expect(within(strip).getAllByRole('button')[5]).toHaveAttribute('aria-current', 'time')
    const selected = screen.getByTestId('popup-selected-hour')
    expect(selected).toHaveTextContent('+5 h')
    expect(within(selected).getByText('High')).toBeVisible()
    expect(selected).toHaveTextContent(/14 mph/)
  })

  it('says so when the selected hour has no forecast', () => {
    renderPopup(40)
    const selected = screen.getByTestId('popup-selected-hour')
    expect(selected).toHaveTextContent(/no forecast for this hour/i)
    expect(within(selected).getByText('No data')).toBeVisible()
  })

  it('shows a loading note before the series arrives', () => {
    renderPopup(0, null)
    expect(screen.getByText(/loading the hourly forecast/i)).toBeVisible()
  })
})

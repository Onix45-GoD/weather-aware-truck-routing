import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Providers } from '@/app/Providers'
import { makeCheckpoint, makeRoute } from '@/test/fixtures'
import { makeFrameCheckpoint } from '@/test/corridorFixtures'

import { CheckpointDetails, type CheckpointFrame } from './CheckpointDetails'

const route = makeRoute()
const checkpoint = makeCheckpoint({ index: 2 })

function renderDetails(frame: CheckpointFrame | null) {
  render(
    <Providers>
      <CheckpointDetails
        route={route}
        checkpoint={checkpoint}
        timeZone="America/Denver"
        weatherDetailAvailable={false}
        frame={frame}
      />
    </Providers>,
  )
}

describe('CheckpointDetails forecast-hour block', () => {
  it('is absent until a corridor frame exists', () => {
    renderDetails(null)
    expect(screen.queryByTestId('checkpoint-frame')).not.toBeInTheDocument()
    expect(screen.getByText(/At ETA · Open-Meteo hourly forecast/)).toBeVisible()
  })

  it('shows the selected hour, its timestamp, measurements and the backend explanation', () => {
    renderDetails({
      hour: 12,
      at: '2026-11-03T01:00:00+00:00',
      available: true,
      checkpoint: makeFrameCheckpoint(2, 'HIGH'),
    })
    const block = screen.getByTestId('checkpoint-frame')
    expect(within(block).getByText(/At \+12 h/)).toBeVisible()
    expect(within(block).getByText(/6:00 PM MST/)).toBeVisible()
    expect(within(block).getByText('14 mph')).toBeVisible()
    expect(within(block).getByText('Gusts 22 mph')).toBeVisible()
    expect(within(block).getByText('High')).toBeVisible()
    expect(within(block).getByText(/Overall HIGH/)).toBeVisible()
    expect(within(block).getByText(/display only/i)).toBeVisible()
  })

  it('keeps the ETA block intact alongside the hour block', () => {
    renderDetails({
      hour: 3,
      at: '2026-11-02T16:00:00+00:00',
      available: true,
      checkpoint: makeFrameCheckpoint(2, 'LOW'),
    })
    expect(screen.getByText(/^Arrives/)).toBeVisible()
    expect(screen.getByText(checkpoint.risk.explanation)).toBeVisible()
  })

  it('says unknown — not clear — when the hour has no forecast', () => {
    renderDetails({
      hour: 40,
      at: '2026-11-04T05:00:00+00:00',
      available: false,
      checkpoint: makeFrameCheckpoint(2, 'UNKNOWN'),
    })
    const block = screen.getByTestId('checkpoint-frame')
    expect(within(block).getByText(/no forecast for this hour/i)).toBeVisible()
    expect(within(block).getByText(/shown as unknown, not as clear/i)).toBeVisible()
    expect(within(block).queryByText('Low')).not.toBeInTheDocument()
  })

  it('renders missing measurements as dashes, never zero', () => {
    renderDetails({
      hour: 5,
      at: '2026-11-02T18:00:00+00:00',
      available: true,
      checkpoint: makeFrameCheckpoint(2, 'LOW', {
        weather: { wind_mph: 8, wind_gust_mph: null, rain_in_hr: null, snow_in_hr: 0, forecast_time: null },
      }),
    })
    const block = screen.getByTestId('checkpoint-frame')
    expect(within(block).getByText('8 mph')).toBeVisible()
    expect(within(block).getAllByText('—').length).toBeGreaterThan(0)
    expect(within(block).getByText('0.00 in/hr')).toBeVisible()
  })

  it('flags a cargo-weight escalation for the hour', () => {
    renderDetails({
      hour: 9,
      at: '2026-11-02T22:00:00+00:00',
      available: true,
      checkpoint: makeFrameCheckpoint(2, 'HIGH', {
        risk: { ...makeFrameCheckpoint(2, 'HIGH').risk, load_override_applied: true },
      }),
    })
    expect(screen.getByText(/cargo weight escalated this hour/i)).toBeVisible()
  })
})

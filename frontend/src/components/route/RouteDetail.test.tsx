import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { makeAnalysis, makeCheckpoint, makeRoutes } from '@/test/fixtures'

import { RouteDetail } from './RouteDetail'

function setup() {
  const routes = makeRoutes(2)
  routes[1] = {
    ...routes[1]!,
    separated_from_previous_by: 'high_miles',
    metrics: { ...routes[1]!.metrics, high_miles: 25, low_miles: 1095 },
    checkpoints: [
      makeCheckpoint({ index: 0, is_origin: true }),
      makeCheckpoint({ index: 1, risk: { ...makeCheckpoint().risk, level: 'HIGH', driver: 'wind' } }),
      makeCheckpoint({ index: 2, is_destination: true }),
    ],
  }
  return makeAnalysis({ routes })
}

describe('RouteDetail', () => {
  it('prompts when nothing is selected', () => {
    render(
      <Providers>
        <RouteDetail analysis={setup()} route={null} />
      </Providers>,
    )
    expect(screen.getByText(/select a route in the comparison table/i)).toBeVisible()
  })

  it('shows the recommended route with the backend reason and headline stats', () => {
    const analysis = setup()
    render(
      <Providers>
        <RouteDetail analysis={analysis} route={analysis.routes[0]!} timeZone="America/Denver" />
      </Providers>,
    )
    expect(screen.getByText('Rank 1 of 2')).toBeVisible()
    expect(screen.getByText('Recommended')).toBeVisible()
    expect(screen.getByTestId('route-why')).toHaveTextContent(analysis.recommendation_reason)
    expect(screen.getByText(/none above low/i)).toBeVisible()
  })

  it('explains a lower rank by the deciding criterion with both values', () => {
    const analysis = setup()
    render(
      <Providers>
        <RouteDetail analysis={analysis} route={analysis.routes[1]!} timeZone="America/Denver" />
      </Providers>,
    )
    expect(screen.getByTestId('route-why')).toHaveTextContent(
      /Ranked 2nd, below Primary route: Severe miles tie \(0 mi\); more High miles \(25 mi vs 0 mi\)/,
    )
  })

  it('draws miles by level and lists the worst checkpoints as jump targets', async () => {
    const analysis = setup()
    const onSelectCheckpoint = vi.fn()
    render(
      <Providers>
        <RouteDetail
          analysis={analysis}
          route={analysis.routes[1]!}
          timeZone="America/Denver"
          onSelectCheckpoint={onSelectCheckpoint}
        />
      </Providers>,
    )
    expect(screen.getByRole('img', { name: /Low 1,095 mi, High 25 mi/ })).toBeInTheDocument()
    const list = screen.getByRole('list', { name: /worst checkpoints/i })
    const items = within(list).getAllByRole('button')
    expect(items).toHaveLength(1)
    expect(items[0]).toHaveTextContent(/Checkpoint 1 · mile 25/)
    expect(within(items[0]!).getByText('High')).toBeVisible()
    await userEvent.setup().click(items[0]!)
    expect(onSelectCheckpoint).toHaveBeenCalledWith(1)
  })

  it('shows the drive window and ETA source', () => {
    const analysis = setup()
    render(
      <Providers>
        <RouteDetail analysis={analysis} route={analysis.routes[0]!} timeZone="America/Denver" />
      </Providers>,
    )
    expect(screen.getByText(/^Departs .* · arrives/)).toBeVisible()
    expect(screen.getByText(/3 checkpoints/)).toBeVisible()
  })

  it('lists ineligibility reasons for a blocked route', () => {
    const analysis = setup()
    const blocked = {
      ...analysis.routes[1]!,
      eligible: false,
      separated_from_previous_by: 'eligibility' as const,
      ineligibility_reasons: ['No Travel conditions over 8.0 mi of this route'],
    }
    render(
      <Providers>
        <RouteDetail analysis={analysis} route={blocked} />
      </Providers>,
    )
    expect(screen.getByText('Not usable')).toBeVisible()
    expect(screen.getByRole('list', { name: /cannot be recommended/i })).toHaveTextContent(/No Travel conditions over 8.0 mi/)
    expect(screen.getByTestId('route-why')).toHaveTextContent(/eligible routes always rank first/)
  })
})

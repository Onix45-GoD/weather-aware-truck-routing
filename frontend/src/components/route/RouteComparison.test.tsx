import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { makeAnalysis, makeRoutes } from '@/test/fixtures'

import { RouteComparison } from './RouteComparison'

function analysisWithCriteria() {
  const routes = makeRoutes(3)
  routes[1] = {
    ...routes[1]!,
    separated_from_previous_by: 'duration_seconds',
  }
  routes[2] = {
    ...routes[2]!,
    eligible: false,
    separated_from_previous_by: 'eligibility',
    ineligibility_reasons: ['No Travel conditions over 8.0 mi of this route'],
    metrics: { ...routes[2]!.metrics, no_travel_miles: 8, blocked: true },
  }
  return makeAnalysis({ routes })
}

function renderTable(selected: string | null = 'tomtom-0') {
  const onSelect = vi.fn()
  render(
    <Providers>
      <RouteComparison analysis={analysisWithCriteria()} selectedRouteId={selected} onSelect={onSelect} />
    </Providers>,
  )
  return { onSelect, table: screen.getByRole('table', { name: /route comparison/i }) }
}

describe('RouteComparison', () => {
  it('lists every route in rank order with the four criteria', () => {
    const { table } = renderTable()
    const rows = within(table).getAllByRole('button')
    expect(rows).toHaveLength(3)
    expect(rows[0]).toHaveAccessibleName(/Primary route, rank 1, recommended/)
    expect(rows[2]).toHaveAccessibleName(/Alternative 2, rank 3, not usable/)
    for (const header of ['Severe mi', 'High mi', 'Avg risk', 'Drive time', 'Coverage', 'Status']) {
      expect(within(table).getByText(header)).toBeInTheDocument()
    }
  })

  it('outlines the cell the backend says decided each row', () => {
    const { table } = renderTable()
    const rows = within(table).getAllByRole('button')
    const deciding = (row: HTMLElement) => row.querySelector('[data-deciding="true"]')
    expect(deciding(rows[0]!)).toBeNull() // rank 1 has nothing above it
    expect(deciding(rows[1]!)).toHaveTextContent('15h 50m') // drive time
    expect(deciding(rows[1]!)).toHaveAttribute('title', expect.stringMatching(/decided vs #1: drive time/))
    expect(deciding(rows[2]!)).toHaveTextContent('Not usable')
  })

  it('marks the selected route and selects on click or keyboard', async () => {
    const { onSelect, table } = renderTable('tomtom-1')
    const rows = within(table).getAllByRole('button')
    expect(rows[1]).toHaveAttribute('aria-current', 'true')
    const user = userEvent.setup()
    await user.click(rows[2]!)
    expect(onSelect).toHaveBeenCalledWith('tomtom-2')
    rows[0]!.focus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenCalledWith('tomtom-0')
  })

  it('states the ranking rule in the header', () => {
    renderTable()
    expect(screen.getByText(/Severe → High → avg risk → time/)).toBeVisible()
  })
})

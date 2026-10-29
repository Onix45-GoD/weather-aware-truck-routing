import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Providers } from '@/app/Providers'
import { makeAnalysis, makeRoutes } from '@/test/fixtures'

import { KpiStrip } from './KpiStrip'

describe('KpiStrip', () => {
  it('shows the route count, the recommendation and the selected route’s metrics', () => {
    const analysis = makeAnalysis({ routes: makeRoutes(3) })
    render(
      <Providers>
        <KpiStrip analysis={analysis} route={analysis.routes[1]!} />
      </Providers>,
    )
    const strip = screen.getByTestId('kpi-strip')
    expect(within(strip).getByText('3')).toBeVisible()
    expect(within(strip).getByText('Primary route')).toBeVisible() // recommended
    expect(within(strip).getByText('Alternative 1')).toBeVisible() // selected
    expect(within(strip).getByText('Total distance')).toBeVisible()
    expect(within(strip).getByText('1,120 mi')).toBeVisible()
    expect(within(strip).getByText('15h 50m')).toBeVisible()
  })

  it('says None when nothing is recommended', () => {
    const analysis = makeAnalysis({ recommended_route_id: null, routes: makeRoutes(1).map((r) => ({ ...r, is_recommended: false })) })
    render(
      <Providers>
        <KpiStrip analysis={analysis} route={null} />
      </Providers>,
    )
    expect(screen.getByText('None')).toBeVisible()
    expect(screen.queryByText('Total distance')).not.toBeInTheDocument()
  })
})

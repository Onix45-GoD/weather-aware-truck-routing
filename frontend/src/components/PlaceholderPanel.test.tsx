import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { PlaceholderPanel } from '@/components/PlaceholderPanel'

describe('PlaceholderPanel', () => {
  it('renders its title, milestone badge and children', () => {
    render(
      <PlaceholderPanel title="Corridor forecast" milestone={6}>
        <p>Heatmap goes here</p>
      </PlaceholderPanel>,
    )

    expect(
      screen.getByRole('heading', { name: 'Corridor forecast', level: 2 }),
    ).toBeInTheDocument()
    expect(screen.getByText('Milestone 6')).toBeInTheDocument()
    expect(screen.getByText('Heatmap goes here')).toBeInTheDocument()
  })

  it('links the region to its heading for assistive technology', () => {
    render(
      <PlaceholderPanel title="Corridor forecast" milestone={6}>
        <p>body</p>
      </PlaceholderPanel>,
    )

    const region = screen.getByRole('region', { name: 'Corridor forecast' })
    expect(region).toHaveAttribute('aria-labelledby', 'panel-corridor-forecast')
  })
})

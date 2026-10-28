import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from '@/App'

describe('App shell', () => {
  it('renders the application title', () => {
    render(<App />)
    expect(
      screen.getByRole('heading', { name: /weather-aware truck routing/i, level: 1 }),
    ).toBeInTheDocument()
  })

  it('renders a region for every planned feature', () => {
    render(<App />)
    for (const name of [/^trip$/i, /^routes$/i, /^map$/i, /corridor forecast/i]) {
      expect(screen.getByRole('region', { name })).toBeInTheDocument()
    }
  })

  it('gives each region an accessible name from its heading', () => {
    render(<App />)
    expect(screen.getAllByRole('region')).toHaveLength(4)
    expect(screen.getAllByRole('heading', { level: 2 })).toHaveLength(4)
  })
})

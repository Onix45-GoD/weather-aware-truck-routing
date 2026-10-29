import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'

import { OnboardingPanel } from './OnboardingPanel'

describe('OnboardingPanel', () => {
  it('explains the three steps, the colours and what each overlay means', () => {
    render(
      <Providers>
        <OnboardingPanel onExample={vi.fn()} onDismiss={vi.fn()} />
      </Providers>,
    )
    expect(screen.getByText('Three steps')).toBeVisible()
    expect(screen.getByText('Enter the trip')).toBeVisible()
    expect(screen.getByText('Analyze')).toBeVisible()
    expect(screen.getByText('Read the result')).toBeVisible()
    expect(screen.getByText(/never counted as safe/i)).toBeVisible()
    expect(screen.getByText('Wide band and halos')).toBeVisible()
    expect(screen.getByText('Corridor timeline')).toBeVisible()
  })

  it('offers an example trip and a dismissal', async () => {
    const onExample = vi.fn()
    const onDismiss = vi.fn()
    render(
      <Providers>
        <OnboardingPanel onExample={onExample} onDismiss={onDismiss} />
      </Providers>,
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /try an example trip/i }))
    expect(onExample).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: /got it/i }))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('disables the example while it runs', () => {
    render(
      <Providers>
        <OnboardingPanel onExample={vi.fn()} onDismiss={vi.fn()} exampleLoading />
      </Providers>,
    )
    expect(screen.getByRole('button', { name: /running/i })).toBeDisabled()
  })
})

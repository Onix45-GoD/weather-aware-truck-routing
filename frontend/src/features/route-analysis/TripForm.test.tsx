import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'

import { TripForm } from './TripForm'

function renderForm(props: Partial<Parameters<typeof TripForm>[0]> = {}) {
  const onSubmit = vi.fn()
  render(
    <Providers>
      <TripForm onSubmit={onSubmit} isLoading={false} {...props} />
    </Providers>,
  )
  return { onSubmit }
}

const submitButton = () => screen.getByRole('button', { name: /analyze routes/i })

describe('TripForm accessibility', () => {
  it('labels every input', () => {
    renderForm()
    expect(screen.getByLabelText(/^origin$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^destination$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/departure date/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/cargo weight/i)).toBeInTheDocument()
  })

  it('has no departure-delay slider; the corridor timeline is the only 0–48 h control', () => {
    renderForm()
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
  })

  it('defaults the departure timezone to a US zone, not the browser zone', () => {
    renderForm()
    expect(screen.getByRole('combobox', { name: /departure timezone/i })).toHaveTextContent('America/Denver')
  })

  it('can be submitted from the keyboard', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    await user.tab()
    submitButton().focus()
    await user.keyboard('{Enter}')

    expect(onSubmit).toHaveBeenCalledTimes(1)
  })
})

describe('TripForm validation', () => {
  it('blocks submission when the origin is blank', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    await user.clear(screen.getByLabelText(/^origin$/i))
    await user.click(submitButton())

    expect(onSubmit).not.toHaveBeenCalled()
    expect(await screen.findByText(/enter a starting location/i)).toBeVisible()
  })

  it('blocks submission when the destination is blank', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    await user.clear(screen.getByLabelText(/^destination$/i))
    await user.click(submitButton())

    expect(onSubmit).not.toHaveBeenCalled()
    expect(await screen.findByText(/enter a destination/i)).toBeVisible()
  })

  it.each([['0'], ['-5'], ['999999']])(
    'rejects an out-of-range cargo weight of %s',
    async (weight) => {
      const user = userEvent.setup()
      const { onSubmit } = renderForm()

      const field = screen.getByLabelText(/cargo weight/i)
      await user.clear(field)
      await user.type(field, weight)
      await user.click(submitButton())

      expect(onSubmit).not.toHaveBeenCalled()
    },
  )

  it('surfaces server field errors against the right input', () => {
    renderForm({
      fieldErrors: {
        departure_timezone: ['Unknown timezone.'],
        load_weight_lb: ['Ensure this value is less than 200000.'],
      },
    })

    expect(screen.getByText('Unknown timezone.')).toBeVisible()
    expect(
      screen.getByText('Ensure this value is less than 200000.'),
    ).toBeVisible()
  })
})

describe('TripForm request serialisation', () => {
  it('sends wall-clock time with an IANA zone, not a UTC guess', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    await user.click(submitButton())

    const payload = onSubmit.mock.calls[0]?.[0]
    expect(payload).toBeDefined()
    // No offset and no `Z`: the server resolves it using the zone, which is
    // what makes daylight saving correct.
    expect(payload.departure_at).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/)
    expect(payload.departure_at).not.toMatch(/Z|[+-]\d{2}:\d{2}$/)
    expect(typeof payload.departure_timezone).toBe('string')
    expect(payload.departure_timezone.length).toBeGreaterThan(0)
  })

  it('sends numbers as numbers', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    await user.click(submitButton())

    const payload = onSubmit.mock.calls[0]?.[0]
    expect(typeof payload.load_weight_lb).toBe('number')
    expect(typeof payload.checkpoint_interval_miles).toBe('number')
    expect(payload).not.toHaveProperty('forecast_offset_hours')
  })

  it('trims surrounding whitespace from locations', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm()

    const origin = screen.getByLabelText(/^origin$/i)
    await user.clear(origin)
    await user.type(origin, '  Denver, CO  ')
    await user.click(submitButton())

    expect(onSubmit.mock.calls[0]?.[0].origin).toBe('Denver, CO')
  })

})

describe('TripForm loading state', () => {
  it('disables the button while an analysis is running', () => {
    renderForm({ isLoading: true })
    expect(screen.getByRole('button', { name: /analysing/i })).toBeDisabled()
  })

  it('does not submit twice while loading', async () => {
    const user = userEvent.setup()
    const { onSubmit } = renderForm({ isLoading: true })

    await user.click(screen.getByRole('button', { name: /analysing/i }))
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

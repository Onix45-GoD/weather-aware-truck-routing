import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'

import { PlaceField } from './PlaceField'

const fetchPlaceSuggestions = vi.hoisted(() => vi.fn())
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, fetchPlaceSuggestions }
})

function Harness({ initial = '' }: { initial?: string }) {
  const [value, setValue] = useState(initial)
  return <PlaceField label="Origin" value={value} onChange={setValue} />
}

function renderField(initial = '') {
  render(
    <Providers>
      <Harness initial={initial} />
    </Providers>,
  )
  return screen.getByRole('combobox', { name: 'Origin' })
}

beforeEach(() => {
  fetchPlaceSuggestions.mockReset()
  fetchPlaceSuggestions.mockResolvedValue({
    query: 'den',
    suggestions: [
      { label: 'Denver, CO, USA', latitude: 39.74, longitude: -104.99 },
      { label: 'Denton, TX, USA', latitude: 33.21, longitude: -97.13 },
    ],
  })
})

describe('PlaceField', () => {
  it('does not search for the initial value on mount', async () => {
    renderField('Denver, CO')
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(fetchPlaceSuggestions).not.toHaveBeenCalled()
  })

  it('does not ask the server for a single character', async () => {
    const input = renderField()
    await userEvent.setup().type(input, 'd')
    await new Promise((resolve) => setTimeout(resolve, 350))
    expect(fetchPlaceSuggestions).not.toHaveBeenCalled()
  })

  it('shows server suggestions after a pause and fills the field on pick', async () => {
    const input = renderField()
    const user = userEvent.setup()
    await user.type(input, 'den')
    await waitFor(() => expect(fetchPlaceSuggestions).toHaveBeenCalled())
    const [query] = fetchPlaceSuggestions.mock.calls.at(-1) as [string]
    expect(query).toBe('den')

    const option = await screen.findByRole('option', { name: /Denver, CO, USA/ })
    await user.click(option)
    expect(input).toHaveValue('Denver, CO, USA')
  })

  it('debounces: one request for a burst of keystrokes', async () => {
    const input = renderField()
    await userEvent.setup().type(input, 'denver')
    await waitFor(() => expect(fetchPlaceSuggestions).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 400))
    expect(fetchPlaceSuggestions).toHaveBeenCalledTimes(1)
    expect((fetchPlaceSuggestions.mock.calls[0] as [string])[0]).toBe('denver')
  })

  it('keeps free text when nothing is picked', async () => {
    fetchPlaceSuggestions.mockResolvedValue({ query: 'xx', suggestions: [] })
    const input = renderField()
    await userEvent.setup().type(input, 'Somewhere odd')
    expect(input).toHaveValue('Somewhere odd')
  })

  it('still carries the typed text when suggestions fail', async () => {
    fetchPlaceSuggestions.mockRejectedValue(new Error('down'))
    const input = renderField()
    await userEvent.setup().type(input, 'Boise')
    await waitFor(() => expect(fetchPlaceSuggestions).toHaveBeenCalled())
    expect(input).toHaveValue('Boise')
  })
})

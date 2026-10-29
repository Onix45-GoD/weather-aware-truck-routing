import PlaceIcon from '@mui/icons-material/Place'
import Autocomplete from '@mui/material/Autocomplete'
import CircularProgress from '@mui/material/CircularProgress'
import TextField from '@mui/material/TextField'
import { useState } from 'react'

import type { PlaceSuggestion } from '@/api/types'

import { usePlaceSuggestions } from './usePlaceSuggestions'

export interface PlaceFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  error?: string | undefined
  disabled?: boolean | undefined
}

/**
 * A place input with server-side suggestions.
 *
 * Free text is always allowed -- the analysis geocodes whatever is
 * submitted -- so the suggestions are an accelerator, never a gate. The
 * list is whatever the geocoder returns, in its order; nothing is filtered
 * or re-ranked on the client.
 */
export function PlaceField({ label, value, onChange, error, disabled }: PlaceFieldProps) {
  // Only after the user types. The default values and a value picked from
  // the list are not queries; fetching for them wastes a call per field.
  const [dirty, setDirty] = useState(false)
  const { options, loading } = usePlaceSuggestions(value, dirty)

  return (
    <Autocomplete<PlaceSuggestion, false, false, true>
      freeSolo
      disabled={disabled}
      options={options}
      // The server already matched; client-side filtering would hide results
      // whose label does not literally contain the typed text.
      filterOptions={(items) => items}
      getOptionLabel={(option) => (typeof option === 'string' ? option : option.label)}
      isOptionEqualToValue={(option, selected) =>
        typeof selected === 'string' ? option.label === selected : option.label === selected.label
      }
      inputValue={value}
      onInputChange={(_event, next, reason) => {
        if (reason === 'input') setDirty(true)
        else if (reason === 'selectOption' || reason === 'reset') setDirty(false)
        onChange(next)
      }}
      onChange={(_event, picked) => {
        if (picked && typeof picked !== 'string') onChange(picked.label)
      }}
      loading={loading}
      loadingText="Searching…"
      noOptionsText={value.trim().length < 2 ? 'Type at least 2 characters' : 'No matches'}
      autoHighlight
      openOnFocus={false}
      size="small"
      renderOption={(props, option) => {
        const { key, ...rest } = props as typeof props & { key: string }
        return (
          <li key={key} {...rest}>
            <PlaceIcon sx={{ fontSize: 16, mr: 1, color: 'text.secondary' }} />
            {option.label}
          </li>
        )
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          error={Boolean(error)}
          helperText={error}
          slotProps={{
            ...params.slotProps,
            htmlInput: {
              ...params.slotProps.htmlInput,
              'aria-label': label,
              autoComplete: 'off',
            },
            input: {
              ...params.slotProps.input,
              endAdornment: (
                <>
                  {loading ? <CircularProgress size={14} color="inherit" /> : null}
                  {params.slotProps.input.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
    />
  )
}

import SearchIcon from '@mui/icons-material/Search'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import { useEffect, useMemo, useState, type FormEvent } from 'react'

import { CHECKPOINT_INTERVALS, type RouteAnalysisRequest } from '@/api/types'
import { PlaceField } from '@/features/places/PlaceField'
import { timezoneOptions } from '@/lib/timezones'
import { PALETTE } from '@/theme/theme'

import { defaultTripValues } from './tripDefaults'
import { clearStoredTrip, loadStoredTrip, storeTrip } from './tripStorage'

export interface TripFormValues {
  origin: string
  destination: string
  /** Local wall-clock, `YYYY-MM-DDTHH:mm`. Never implicitly UTC. */
  departureLocal: string
  departureTimezone: string
  loadWeightLb: string
  checkpointIntervalMiles: number
}

export interface TripFormProps {
  onSubmit: (payload: RouteAnalysisRequest) => void
  isLoading: boolean
  /** Field-level errors returned by the API, keyed by request field name. */
  fieldErrors?: Record<string, string[]> | undefined
  /** Overrides both the defaults and the remembered trip. */
  initialValues?: Partial<TripFormValues> | undefined
}

const LOCAL_ERRORS = {
  origin: 'Enter a starting location.',
  destination: 'Enter a destination.',
  departureLocal: 'Choose a departure date and time.',
  loadWeightLb: 'Enter a cargo weight between 1 and 200,000 lb.',
} as const

export function TripForm({
  onSubmit,
  isLoading,
  fieldErrors = {},
  initialValues,
}: TripFormProps) {
  // Precedence: explicit seed (the example trip) > what the user typed last
  // time (survives a refresh) > defaults.
  const [values, setValues] = useState<TripFormValues>(() => ({
    ...defaultTripValues(),
    ...loadStoredTrip(),
    ...initialValues,
  }))
  const [touched, setTouched] = useState(false)

  useEffect(() => {
    storeTrip(values)
  }, [values])

  const zones = useMemo(() => timezoneOptions(), [])

  const localErrors = useMemo(() => {
    const weight = Number(values.loadWeightLb)
    return {
      origin: values.origin.trim() ? '' : LOCAL_ERRORS.origin,
      destination: values.destination.trim() ? '' : LOCAL_ERRORS.destination,
      departureLocal: values.departureLocal ? '' : LOCAL_ERRORS.departureLocal,
      loadWeightLb:
        Number.isFinite(weight) && weight >= 1 && weight <= 200_000
          ? ''
          : LOCAL_ERRORS.loadWeightLb,
    }
  }, [values])

  const hasLocalErrors = Object.values(localErrors).some(Boolean)

  /** Server message for a field, falling back to the local one.
   *
   * `apiField` is the *request* field name, which differs from the form
   * field name (`departureLocal` vs `departure_at`), so the server's
   * field-level errors land on the right input.
   */
  const errorFor = (
    field: keyof typeof localErrors,
    apiField: string = field,
  ): string => {
    const fromApi = fieldErrors[apiField]?.[0]
    if (fromApi) return fromApi
    return touched ? localErrors[field] : ''
  }

  const update = <K extends keyof TripFormValues>(
    key: K,
    value: TripFormValues[K],
  ) => setValues((previous) => ({ ...previous, [key]: value }))

  const reset = () => {
    clearStoredTrip()
    setValues(defaultTripValues())
    setTouched(false)
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault()
    setTouched(true)
    if (hasLocalErrors || isLoading) return

    onSubmit({
      origin: values.origin.trim(),
      destination: values.destination.trim(),
      // Sent as naive wall-clock time *with* the zone name. The server
      // resolves it, including daylight saving — which a client-computed
      // UTC offset gets wrong across a DST boundary.
      departure_at: values.departureLocal,
      departure_timezone: values.departureTimezone,
      load_weight_lb: Number(values.loadWeightLb),
      checkpoint_interval_miles:
        values.checkpointIntervalMiles as RouteAnalysisRequest['checkpoint_interval_miles'],
    })
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <PlaceField
        label="Origin"
        value={values.origin}
        onChange={(value) => update('origin', value)}
        error={errorFor('origin') || undefined}
      />

      <PlaceField
        label="Destination"
        value={values.destination}
        onChange={(value) => update('destination', value)}
        error={errorFor('destination') || undefined}
      />

      <TextField
        label="Departure"
        type="datetime-local"
        value={values.departureLocal}
        onChange={(event) => update('departureLocal', event.target.value)}
        error={Boolean(errorFor('departureLocal', 'departure_at'))}
        helperText={errorFor('departureLocal', 'departure_at') || undefined}
        fullWidth
        size="small"
        slotProps={{ inputLabel: { shrink: true } }}
      />

      <TextField
        select
        label="Timezone"
        value={values.departureTimezone}
        onChange={(event) => update('departureTimezone', event.target.value)}
        error={Boolean(fieldErrors['departure_timezone']?.[0])}
        helperText={fieldErrors['departure_timezone']?.[0]}
        fullWidth
        size="small"
        slotProps={{ htmlInput: { 'aria-label': 'Departure timezone' } }}
      >
        {zones.map((zone) => (
          <MenuItem key={zone.value} value={zone.value}>
            {zone.label}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        label="Cargo weight (lb)"
        type="number"
        value={values.loadWeightLb}
        onChange={(event) => update('loadWeightLb', event.target.value)}
        error={Boolean(errorFor('loadWeightLb', 'load_weight_lb'))}
        helperText={errorFor('loadWeightLb', 'load_weight_lb') || undefined}
        fullWidth
        size="small"
        slotProps={{ htmlInput: { min: 1, max: 200000, step: 500 } }}
      />

      <TextField
        select
        label="Checkpoint every"
        value={values.checkpointIntervalMiles}
        onChange={(event) =>
          update('checkpointIntervalMiles', Number(event.target.value))
        }
        fullWidth
        size="small"
      >
        {CHECKPOINT_INTERVALS.map((interval) => (
          <MenuItem key={interval} value={interval}>
            {interval} miles
          </MenuItem>
        ))}
      </TextField>

      <Button
        type="submit"
        variant="contained"
        size="large"
        disabled={isLoading}
        startIcon={
          isLoading ? (
            <CircularProgress size={18} color="inherit" />
          ) : (
            <SearchIcon />
          )
        }
        fullWidth
        sx={{
          background: PALETTE.brandGradient,
          color: '#1A0E00',
          '&.Mui-disabled': { background: PALETTE.elevated, color: PALETTE.textSecondary },
        }}
      >
        {isLoading ? 'Analysing…' : 'Analyze Routes'}
      </Button>

      <Button
        type="button"
        variant="text"
        size="small"
        onClick={reset}
        sx={{ alignSelf: 'flex-start', color: PALETTE.textSecondary, minHeight: 0 }}
      >
        Reset
      </Button>
    </form>
  )
}

import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import SearchIcon from '@mui/icons-material/Search'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import MenuItem from '@mui/material/MenuItem'
import Slider from '@mui/material/Slider'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useId, useMemo, useState, type FormEvent } from 'react'

import { CHECKPOINT_INTERVALS, type RouteAnalysisRequest } from '@/api/types'
import { browserTimezone, timezoneOptions } from '@/lib/timezones'

export interface TripFormValues {
  origin: string
  destination: string
  /** Local wall-clock, `YYYY-MM-DDTHH:mm`. Never implicitly UTC. */
  departureLocal: string
  departureTimezone: string
  loadWeightLb: string
  checkpointIntervalMiles: number
  forecastOffsetHours: number
}

export interface TripFormProps {
  onSubmit: (payload: RouteAnalysisRequest) => void
  isLoading: boolean
  /** Field-level errors returned by the API, keyed by request field name. */
  fieldErrors?: Record<string, string[]> | undefined
  initialValues?: Partial<TripFormValues> | undefined
}

function defaultDeparture(): string {
  const when = new Date(Date.now() + 2 * 60 * 60 * 1000)
  when.setMinutes(0, 0, 0)
  // `toISOString` would convert to UTC; we want the *local* wall clock.
  const pad = (value: number) => String(value).padStart(2, '0')
  return (
    `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}` +
    `T${pad(when.getHours())}:${pad(when.getMinutes())}`
  )
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
  const [values, setValues] = useState<TripFormValues>(() => ({
    origin: 'Denver, CO',
    destination: 'Chicago, IL',
    departureLocal: defaultDeparture(),
    departureTimezone: browserTimezone(),
    loadWeightLb: '40000',
    checkpointIntervalMiles: 25,
    forecastOffsetHours: 0,
    ...initialValues,
  }))
  const [touched, setTouched] = useState(false)

  const zones = useMemo(() => timezoneOptions(), [])
  const offsetLabelId = useId()

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
      forecast_offset_hours: values.forecastOffsetHours,
    })
  }

  return (
    <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-4">
      <TextField
        label="Origin"
        value={values.origin}
        onChange={(event) => update('origin', event.target.value)}
        error={Boolean(errorFor('origin'))}
        helperText={errorFor('origin')}
        fullWidth
        size="small"
        autoComplete="off"
        slotProps={{ htmlInput: { 'aria-label': 'Origin' } }}
      />

      <TextField
        label="Destination"
        value={values.destination}
        onChange={(event) => update('destination', event.target.value)}
        error={Boolean(errorFor('destination'))}
        helperText={errorFor('destination')}
        fullWidth
        size="small"
        autoComplete="off"
        slotProps={{ htmlInput: { 'aria-label': 'Destination' } }}
      />

      <TextField
        label="Departure date & time"
        type="datetime-local"
        value={values.departureLocal}
        onChange={(event) => update('departureLocal', event.target.value)}
        error={Boolean(errorFor('departureLocal', 'departure_at'))}
        helperText={
          errorFor('departureLocal', 'departure_at') ||
          'Local time in the timezone below'
        }
        fullWidth
        size="small"
        slotProps={{ inputLabel: { shrink: true } }}
      />

      <TextField
        select
        label="Departure timezone"
        value={values.departureTimezone}
        onChange={(event) => update('departureTimezone', event.target.value)}
        error={Boolean(fieldErrors['departure_timezone']?.[0])}
        helperText={
          fieldErrors['departure_timezone']?.[0] ??
          'Daylight saving is applied by the server'
        }
        fullWidth
        size="small"
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
        helperText={
          errorFor('loadWeightLb', 'load_weight_lb') ||
          'Cargo only — not gross vehicle weight'
        }
        fullWidth
        size="small"
        slotProps={{ htmlInput: { min: 1, max: 200000, step: 500 } }}
      />

      <TextField
        select
        label="Checkpoint interval"
        value={values.checkpointIntervalMiles}
        onChange={(event) =>
          update('checkpointIntervalMiles', Number(event.target.value))
        }
        fullWidth
        size="small"
        helperText="How often weather is sampled along the route"
      >
        {CHECKPOINT_INTERVALS.map((interval) => (
          <MenuItem key={interval} value={interval}>
            {interval} miles
          </MenuItem>
        ))}
      </TextField>

      <div className="flex flex-col gap-1">
        {/* The tooltip hangs off its own icon rather than wrapping the
            label. Wrapping the label would make the tooltip text become the
            slider's accessible name, replacing "Delay departure" with a
            paragraph — and a tooltip on plain text is undiscoverable anyway. */}
        <div className="flex items-center gap-1">
          <Typography
            id={offsetLabelId}
            variant="body2"
            className="text-[0.8125rem]"
            color="text.secondary"
          >
            Delay departure (hours)
          </Typography>
          <Tooltip
            title={
              'Re-runs the whole analysis for a later departure — routing, ' +
              'ETAs, weather and the recommendation can all change. This is ' +
              'not a display-only forecast scrubber.'
            }
            placement="top"
          >
            <InfoOutlinedIcon
              aria-label="What does delaying departure do?"
              tabIndex={0}
              sx={{ fontSize: 15, color: 'text.secondary', cursor: 'help' }}
            />
          </Tooltip>
        </div>
        <div className="px-1">
          <Slider
            value={values.forecastOffsetHours}
            onChange={(_event, value) =>
              update('forecastOffsetHours', value as number)
            }
            min={0}
            max={48}
            step={1}
            marks={[
              { value: 0, label: '0' },
              { value: 12, label: '12' },
              { value: 24, label: '24' },
              { value: 36, label: '36' },
              { value: 48, label: '48' },
            ]}
            valueLabelDisplay="auto"
            aria-labelledby={offsetLabelId}
            aria-valuetext={`${values.forecastOffsetHours} hours later`}
          />
        </div>
        {values.forecastOffsetHours > 0 && (
          <Alert severity="info" variant="outlined" className="mt-1">
            Analysing a departure {values.forecastOffsetHours} h later than the
            time above.
          </Alert>
        )}
      </div>

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
      >
        {isLoading ? 'Analysing…' : 'Analyze Routes'}
      </Button>
    </form>
  )
}

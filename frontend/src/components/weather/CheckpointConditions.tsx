import AirIcon from '@mui/icons-material/Air'
import CompressIcon from '@mui/icons-material/Compress'
import OpacityIcon from '@mui/icons-material/Opacity'
import VisibilityIcon from '@mui/icons-material/Visibility'
import WbCloudyIcon from '@mui/icons-material/WbCloudy'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import Alert from '@mui/material/Alert'
import Skeleton from '@mui/material/Skeleton'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Typography from '@mui/material/Typography'
import { useState, type ReactNode } from 'react'

import type {
  Checkpoint,
  CheckpointWeatherResponse,
  ForecastSlot,
} from '@/api/types'
import type { CheckpointWeatherState } from '@/features/checkpoint-weather/useCheckpointWeather'
import { clockTime, compassPoint, measurement } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

import { WeatherIcon } from './weatherIcon'

type Unit = 'F' | 'C'

function toUnit(fahrenheit: number | null, unit: Unit): string {
  if (fahrenheit === null) return '—'
  const value = unit === 'F' ? fahrenheit : ((fahrenheit - 32) * 5) / 9
  return `${Math.round(value)}°`
}

function gapLabel(minutes: number): string {
  const abs = Math.abs(minutes)
  const text = abs >= 60 ? `${Math.floor(abs / 60)}h ${abs % 60}m` : `${abs}m`
  return minutes < 0 ? `${text} before ETA` : `${text} after ETA`
}

function Stat({
  icon,
  label,
  value,
}: {
  icon: ReactNode
  label: string
  value: string
}) {
  return (
    <div
      className="flex flex-col gap-0.5 rounded-lg border border-hairline px-3 py-2"
      style={{ backgroundColor: PALETTE.elevated }}
    >
      <span className="flex items-center gap-1 text-[0.6875rem] text-muted">
        {icon}
        {label}
      </span>
      <span className="text-sm font-semibold tabular-nums">{value}</span>
    </div>
  )
}

/** Index of the slot the strip should centre on: the ETA slot, else the first. */
function focusIndex(data: CheckpointWeatherResponse): number {
  if (!data.at_eta) return 0
  const at = data.at_eta.at
  const index = data.forecast.findIndex((slot) => slot.at === at)
  return index < 0 ? 0 : index
}

/** Up to nine slots around the focus — roughly a day — so the strip stays readable. */
function windowAround(slots: ForecastSlot[], focus: number, size = 9): ForecastSlot[] {
  const start = Math.max(0, Math.min(focus - Math.floor(size / 2), slots.length - size))
  return slots.slice(start, start + size)
}

export interface CheckpointConditionsProps {
  checkpoint: Checkpoint
  weather: CheckpointWeatherState
  /** False when the server has no OpenWeatherMap key. */
  available: boolean
  timeZone?: string | null | undefined
}

/**
 * The weather at a checkpoint, as a driver would ask for it.
 *
 * Two moments are shown and kept apart on purpose: **now** (observed) and
 * **at ETA** (the 3-hourly forecast slot nearest the arrival time). The
 * route's risk colour is *neither* of these — it is the hourly Open-Meteo
 * forecast at ETA through the assessment's thresholds — so this panel is
 * context, not the verdict, and says so.
 */
export function CheckpointConditions({
  checkpoint,
  weather,
  available,
  timeZone,
}: CheckpointConditionsProps) {
  const [unit, setUnit] = useState<Unit>('F')

  if (!available) {
    return (
      <Typography variant="caption" component="p" color="text.secondary">
        Detailed conditions need <code>OPENWEATHERMAP_API_KEY</code> on the
        server. Risk inputs above come from Open-Meteo and are unaffected.
      </Typography>
    )
  }

  if (weather.status === 'loading' || weather.status === 'idle') {
    return (
      <div className="flex flex-col gap-2" aria-busy="true" aria-label="Loading weather">
        <Skeleton variant="rounded" height={88} />
        <Skeleton variant="rounded" height={56} />
      </div>
    )
  }

  if (weather.status === 'unavailable') {
    return (
      <Alert severity="info" variant="outlined">
        Detailed conditions are switched off on this server. Risk inputs above
        are unaffected.
      </Alert>
    )
  }

  if (weather.status === 'error' || !weather.data) {
    return (
      <Alert severity="warning" variant="outlined">
        {weather.error?.message ?? 'Could not load the weather here.'}
      </Alert>
    )
  }

  const data = weather.data
  const now = data.current
  const eta = data.at_eta
  const strip = windowAround(data.forecast, focusIndex(data))
  const wind = (mph: number | null, deg: number | null) => {
    const base = measurement(mph, 'mph', 0)
    const point = compassPoint(deg)
    return point && mph !== null ? `${base} ${point}` : base
  }

  return (
    <div className="flex flex-col gap-3" data-testid="checkpoint-conditions">
      <div className="flex items-center justify-between gap-2">
        <Typography variant="caption" component="p">
          Conditions{data.place_name ? ` near ${data.place_name}` : ''}
        </Typography>
        <ToggleButtonGroup
          exclusive
          size="small"
          aria-label="Temperature unit"
          value={unit}
          onChange={(_event, value: Unit | null) => {
            if (value) setUnit(value)
          }}
          sx={{ '& .MuiToggleButton-root': { px: 1, py: 0, fontSize: '0.7rem' } }}
        >
          <ToggleButton value="F" aria-label="Fahrenheit">°F</ToggleButton>
          <ToggleButton value="C" aria-label="Celsius">°C</ToggleButton>
        </ToggleButtonGroup>
      </div>

      {/* Now | At ETA — the two moments, side by side and labelled. */}
      <div className="grid grid-cols-2 gap-2">
        <div
          className="flex flex-col gap-1 rounded-lg border border-hairline p-3"
          style={{ backgroundColor: PALETTE.elevated }}
        >
          <span className="text-[0.6875rem] uppercase tracking-wide text-muted">
            Now · {clockTime(now.observed_at, timeZone)}
          </span>
          <div className="flex items-center gap-2">
            <WeatherIcon
              code={now.icon}
              condition={now.condition}
              sx={{ fontSize: 34, color: PALETTE.textPrimary }}
            />
            <span className="text-3xl font-semibold tabular-nums leading-none">
              {toUnit(now.temp_f, unit)}
            </span>
          </div>
          <span className="text-sm capitalize">{now.description}</span>
          <span className="text-xs text-muted">
            Feels like {toUnit(now.feels_like_f, unit)}
          </span>
        </div>

        <div
          className="flex flex-col gap-1 rounded-lg border border-hairline p-3"
          style={{ backgroundColor: PALETTE.elevated }}
        >
          <span className="text-[0.6875rem] uppercase tracking-wide text-muted">
            At ETA · {clockTime(checkpoint.eta, timeZone)}
          </span>
          {eta ? (
            <>
              <div className="flex items-center gap-2">
                <WeatherIcon
                  code={eta.icon}
                  condition={eta.condition}
                  sx={{ fontSize: 34, color: PALETTE.textPrimary }}
                />
                <span className="text-3xl font-semibold tabular-nums leading-none">
                  {toUnit(eta.temp_f, unit)}
                </span>
              </div>
              <span className="text-sm capitalize">{eta.description}</span>
              <span className="text-xs text-muted">
                {eta.precipitation_probability !== null
                  ? `${Math.round(eta.precipitation_probability * 100)}% chance of precipitation`
                  : 'Precipitation chance unknown'}
                {data.eta_gap_minutes !== null && data.eta_gap_minutes !== 0
                  ? ` · slot ${gapLabel(data.eta_gap_minutes)}`
                  : ''}
              </span>
            </>
          ) : (
            <span className="text-xs text-muted">
              {data.eta_beyond_horizon
                ? 'Beyond the 5-day forecast window.'
                : 'No forecast slot near this ETA.'}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <Stat icon={<AirIcon sx={{ fontSize: 13 }} />} label="Wind" value={wind(now.wind_mph, now.wind_deg)} />
        <Stat icon={<OpacityIcon sx={{ fontSize: 13 }} />} label="Humidity" value={now.humidity_pct !== null ? `${now.humidity_pct}%` : '—'} />
        <Stat icon={<VisibilityIcon sx={{ fontSize: 13 }} />} label="Visibility" value={measurement(now.visibility_miles, 'mi', 1)} />
        <Stat icon={<CompressIcon sx={{ fontSize: 13 }} />} label="Pressure" value={now.pressure_hpa !== null ? `${now.pressure_hpa} hPa` : '—'} />
        <Stat icon={<WbCloudyIcon sx={{ fontSize: 13 }} />} label="Clouds" value={now.cloud_pct !== null ? `${now.cloud_pct}%` : '—'} />
        <Stat
          icon={<WaterDropIcon sx={{ fontSize: 13 }} />}
          label={now.snow_in_last_hour !== null ? 'Snow, last hour' : 'Rain, last hour'}
          value={
            now.snow_in_last_hour !== null
              ? measurement(now.snow_in_last_hour, 'in', 2)
              : now.rain_in_last_hour !== null
                ? measurement(now.rain_in_last_hour, 'in', 2)
                : '0 in'
          }
        />
      </div>

      {strip.length > 0 && (
        <div>
          <Typography variant="caption" component="p" className="mb-1">
            3-hourly forecast around ETA
          </Typography>
          <ul
            className="m-0 flex list-none gap-1.5 overflow-x-auto p-0 pb-1"
            aria-label="Forecast around ETA"
          >
            {strip.map((slot) => {
              const isEta = eta !== null && slot.at === eta.at
              return (
                <li
                  key={slot.at}
                  aria-current={isEta ? 'time' : undefined}
                  className="flex min-w-[3.6rem] flex-col items-center gap-0.5 rounded-lg border px-2 py-2 text-center"
                  style={{
                    backgroundColor: PALETTE.elevated,
                    borderColor: isEta ? PALETTE.primary : PALETTE.border,
                  }}
                >
                  <span className="text-[0.6875rem] text-muted">
                    {clockTime(slot.at, timeZone)}
                  </span>
                  <WeatherIcon code={slot.icon} condition={slot.condition} sx={{ fontSize: 18 }} />
                  <span className="text-[0.6875rem] text-muted">
                    {slot.precipitation_probability !== null
                      ? `${Math.round(slot.precipitation_probability * 100)}%`
                      : '—'}
                  </span>
                  <span className="text-sm font-semibold tabular-nums">
                    {toUnit(slot.temp_f, unit)}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      )}

      <Typography variant="caption" component="p" color="text.secondary">
        OpenWeatherMap, observed {clockTime(now.observed_at, timeZone)}. Context
        only — the risk level above is computed from Open-Meteo&rsquo;s hourly
        forecast and is unaffected by this panel.
      </Typography>
    </div>
  )
}

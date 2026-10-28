import AirIcon from '@mui/icons-material/Air'
import AcUnitIcon from '@mui/icons-material/AcUnit'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import Alert from '@mui/material/Alert'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'

import type {
  AnalysedRoute,
  Checkpoint,
  CorridorFrameCheckpoint,
} from '@/api/types'
import { RiskChip } from '@/components/route/RiskChip'
import { useCheckpointWeather } from '@/features/checkpoint-weather/useCheckpointWeather'
import { dateTime, measurement, zoneAbbreviation } from '@/lib/format'
import { frameLabel } from '@/features/corridor/frameLabel'
import { PALETTE } from '@/theme/theme'

import { CheckpointConditions } from './CheckpointConditions'

interface ConditionProps {
  icon: ReactNode
  label: string
  value: string
  secondary?: string | undefined
  unavailable: boolean
}

function Condition({
  icon,
  label,
  value,
  secondary,
  unavailable,
}: ConditionProps) {
  return (
    <div
      className="flex flex-col gap-1 rounded-lg border border-hairline p-3"
      style={{ backgroundColor: PALETTE.elevated }}
    >
      <div className="flex items-center gap-1.5 text-muted">
        {icon}
        <span className="text-xs">{label}</span>
      </div>
      <span
        className="text-base font-semibold tabular-nums"
        style={unavailable ? { color: PALETTE.textSecondary } : undefined}
      >
        {value}
      </span>
      {secondary && <span className="text-[0.6875rem] text-muted">{secondary}</span>}
    </div>
  )
}

export interface CheckpointDetailsProps {
  route: AnalysedRoute | null
  checkpoint: Checkpoint | null
  timeZone?: string | null | undefined
  /** Whether the server can serve detailed conditions (OpenWeatherMap key). */
  weatherDetailAvailable?: boolean | undefined
  /**
   * This checkpoint at the forecast hour the timeline has selected. Null
   * when no corridor forecast is loaded.
   */
  frame?: CheckpointFrame | null | undefined
}

/** The selected forecast hour, narrowed to one checkpoint. */
export interface CheckpointFrame {
  hour: number
  at: string
  /** False when the provider had nothing for this hour at all. */
  available: boolean
  /** Null when the frame has no entry for this checkpoint. */
  checkpoint: CorridorFrameCheckpoint | null
}

/**
 * Detail for one checkpoint.
 *
 * The risk explanation is the backend's own sentence, shown verbatim. It
 * already states which condition drove the level and whether a cargo-weight
 * rule escalated it — rewriting it here would mean maintaining a second
 * description of rules this app does not own.
 */
export function CheckpointDetails({
  route,
  checkpoint,
  timeZone,
  weatherDetailAvailable = false,
  frame = null,
}: CheckpointDetailsProps) {
  // Hooks before the early return; the hook itself is a no-op when there is
  // no checkpoint or the feature is off.
  const detail = useCheckpointWeather(checkpoint, weatherDetailAvailable)

  if (!route || !checkpoint) {
    return (
      <Paper className="p-4">
        <Typography variant="h2" className="mb-2">
          Checkpoint
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Select a checkpoint on the map or in the table to see its forecast.
        </Typography>
      </Paper>
    )
  }

  const weather = checkpoint.weather
  const zone = zoneAbbreviation(checkpoint.eta, timeZone)

  return (
    <Paper className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Typography variant="h2">
            Checkpoint {checkpoint.index}
            {checkpoint.is_origin && ' · Origin'}
            {checkpoint.is_destination && ' · Destination'}
          </Typography>
          <Typography variant="caption" component="p">
            Mile {checkpoint.distance_from_origin_miles.toFixed(0)} ·{' '}
            {checkpoint.latitude.toFixed(4)}, {checkpoint.longitude.toFixed(4)}
          </Typography>
        </div>
        <RiskChip
          level={checkpoint.risk.level}
          size="medium"
          title={
            checkpoint.risk.driver
              ? `Driven by ${checkpoint.risk.driver}`
              : undefined
          }
        />
      </div>

      <Typography variant="body2">
        Arrives {dateTime(checkpoint.eta, timeZone)}
        {zone ? ` ${zone}` : ''}
      </Typography>
      <Typography variant="caption" component="p">
        At ETA · Open-Meteo hourly forecast · this is what the risk level and
        recommendation are computed from
      </Typography>

      {weather ? (
        <div className="grid grid-cols-3 gap-2">
          <Condition
            icon={<AirIcon sx={{ fontSize: 16 }} />}
            label="Wind"
            value={measurement(weather.wind_mph, 'mph', 0)}
            secondary={
              weather.wind_gust_mph !== null
                ? `Gusts ${weather.wind_gust_mph.toFixed(0)} mph`
                : undefined
            }
            unavailable={weather.wind_mph === null}
          />
          <Condition
            icon={<WaterDropIcon sx={{ fontSize: 16 }} />}
            label="Rain"
            value={measurement(weather.rain_in_hr, 'in/hr', 2)}
            unavailable={weather.rain_in_hr === null}
          />
          <Condition
            icon={<AcUnitIcon sx={{ fontSize: 16 }} />}
            label="Snow"
            value={measurement(weather.snow_in_hr, 'in/hr', 2)}
            unavailable={weather.snow_in_hr === null}
          />
        </div>
      ) : (
        <Alert severity="info" variant="outlined" icon={<WarningAmberIcon />}>
          No forecast was available for this checkpoint. Its miles are excluded
          from the risk average rather than counted as clear.
        </Alert>
      )}

      {checkpoint.risk.load_override_applied && (
        <Alert severity="warning" variant="outlined">
          Cargo weight escalated this checkpoint&rsquo;s risk level.
        </Alert>
      )}

      {checkpoint.risk.partial_data && weather && (
        <Alert severity="info" variant="outlined">
          Some measurements were unavailable here; the risk level uses only
          what was reported.
        </Alert>
      )}

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Why this level
        </Typography>
        <Typography variant="body2">{checkpoint.risk.explanation}</Typography>
      </div>

      {frame && (
        <CheckpointFrameBlock frame={frame} timeZone={timeZone} />
      )}

      <CheckpointConditions
        checkpoint={checkpoint}
        weather={detail}
        available={weatherDetailAvailable}
        timeZone={timeZone}
      />
    </Paper>
  )
}


/**
 * The same checkpoint at the hour the corridor timeline has selected.
 *
 * Kept visually parallel to the ETA block above it -- same three conditions,
 * same chip, same explanation sentence from the backend -- so a driver can
 * compare "when I get there" with "at +N h" directly. It is the same
 * provider and the same classifier; only the instant differs, and that is
 * stated in the heading.
 */
function CheckpointFrameBlock({
  frame,
  timeZone,
}: {
  frame: CheckpointFrame
  timeZone?: string | null | undefined
}) {
  const point = frame.checkpoint
  const weather = point?.weather ?? null
  const stamp = frameLabel(frame.at, timeZone)

  return (
    <div
      className="flex flex-col gap-2 rounded-lg border border-hairline p-3"
      data-testid="checkpoint-frame"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <Typography variant="body2" component="p" className="font-semibold">
            At +{frame.hour} h · {stamp}
          </Typography>
          <Typography variant="caption" component="p">
            Selected forecast hour · Open-Meteo hourly · display only
          </Typography>
        </div>
        {point && (
          <RiskChip
            level={point.risk.level}
            size="medium"
            title={point.risk.driver ? `Driven by ${point.risk.driver}` : undefined}
          />
        )}
      </div>

      {!frame.available || !point ? (
        <Alert severity="info" variant="outlined" icon={<WarningAmberIcon />}>
          The provider has no forecast for this hour here. Shown as unknown,
          not as clear.
        </Alert>
      ) : weather ? (
        <div className="grid grid-cols-3 gap-2">
          <Condition
            icon={<AirIcon sx={{ fontSize: 16 }} />}
            label="Wind"
            value={measurement(weather.wind_mph, 'mph', 0)}
            secondary={
              weather.wind_gust_mph !== null
                ? `Gusts ${weather.wind_gust_mph.toFixed(0)} mph`
                : undefined
            }
            unavailable={weather.wind_mph === null}
          />
          <Condition
            icon={<WaterDropIcon sx={{ fontSize: 16 }} />}
            label="Rain"
            value={measurement(weather.rain_in_hr, 'in/hr', 2)}
            unavailable={weather.rain_in_hr === null}
          />
          <Condition
            icon={<AcUnitIcon sx={{ fontSize: 16 }} />}
            label="Snow"
            value={measurement(weather.snow_in_hr, 'in/hr', 2)}
            unavailable={weather.snow_in_hr === null}
          />
        </div>
      ) : (
        <Alert severity="info" variant="outlined" icon={<WarningAmberIcon />}>
          No measurements for this checkpoint at this hour.
        </Alert>
      )}

      {point && point.risk.load_override_applied && (
        <Alert severity="warning" variant="outlined">
          Cargo weight escalated this hour&rsquo;s risk level.
        </Alert>
      )}

      {point && (
        <Typography variant="body2">{point.risk.explanation}</Typography>
      )}
    </div>
  )
}

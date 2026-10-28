import AirIcon from '@mui/icons-material/Air'
import AcUnitIcon from '@mui/icons-material/AcUnit'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import Alert from '@mui/material/Alert'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'

import type { AnalysedRoute, Checkpoint } from '@/api/types'
import { RiskChip } from '@/components/route/RiskChip'
import { dateTime, measurement, zoneAbbreviation } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

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
}: CheckpointDetailsProps) {
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
    </Paper>
  )
}

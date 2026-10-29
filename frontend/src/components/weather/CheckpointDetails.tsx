import AirIcon from '@mui/icons-material/Air'
import AcUnitIcon from '@mui/icons-material/AcUnit'
import WarningAmberIcon from '@mui/icons-material/WarningAmber'
import WaterDropIcon from '@mui/icons-material/WaterDrop'
import Alert from '@mui/material/Alert'
import Paper from '@mui/material/Paper'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import Typography from '@mui/material/Typography'
import type { ReactNode } from 'react'

import type { AnalysedRoute, Checkpoint } from '@/api/types'
import { RiskChip } from '@/components/route/RiskChip'
import type { CheckpointHour } from '@/features/corridor/series'
import { clockTime, dateTime, measurement, zoneAbbreviation } from '@/lib/format'
import { PALETTE } from '@/theme/theme'

function Condition({
  icon,
  label,
  value,
  secondary,
  unavailable,
}: {
  icon: ReactNode
  label: string
  value: string
  secondary?: string | undefined
  unavailable: boolean
}) {
  return (
    <div
      className="flex flex-col gap-0.5 rounded-lg border border-hairline px-3 py-2"
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
  /** This checkpoint across the corridor's 49 hours; null while loading. */
  series?: CheckpointHour[] | null | undefined
  /** The timeline's selected hour, highlighted in the hourly table. */
  hour?: number | undefined
  onHourChange?: ((hour: number) => void) | undefined
}

/**
 * Detail for one checkpoint: what it is like **at ETA** (the input to the
 * recommendation) and the **next 48 hours at this spot** from the corridor
 * forecast. Same provider, same classifier; the table just shows every
 * hour rather than the one the truck arrives at.
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
  series = null,
  hour = 0,
  onHourChange,
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
            Mile {checkpoint.distance_from_origin_miles.toFixed(0)} · arrives{' '}
            {dateTime(checkpoint.eta, timeZone)}
            {zone ? ` ${zone}` : ''}
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

      {weather ? (
        <div className="grid grid-cols-3 gap-2">
          <Condition
            icon={<AirIcon sx={{ fontSize: 16 }} />}
            label="Wind at ETA"
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
            label="Rain at ETA"
            value={measurement(weather.rain_in_hr, 'in/hr', 2)}
            unavailable={weather.rain_in_hr === null}
          />
          <Condition
            icon={<AcUnitIcon sx={{ fontSize: 16 }} />}
            label="Snow at ETA"
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

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Why this level
        </Typography>
        <Typography variant="body2">{checkpoint.risk.explanation}</Typography>
      </div>

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Next 48 h here · Open-Meteo hourly · click a row to move the timeline
        </Typography>
        {series ? (
          <div className="scroll-area max-h-[16rem] rounded-lg border border-hairline">
            <Table size="small" stickyHeader aria-label="Hourly forecast at this checkpoint">
              <TableHead>
                <TableRow>
                  <TableCell>Hour</TableCell>
                  <TableCell>Time</TableCell>
                  <TableCell align="right">Wind</TableCell>
                  <TableCell align="right">Rain</TableCell>
                  <TableCell align="right">Snow</TableCell>
                  <TableCell>Risk</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {series.map((item) => {
                  const isSelected = item.hour === hour
                  const level = item.available ? (item.risk?.level ?? 'UNKNOWN') : 'UNKNOWN'
                  return (
                    <TableRow
                      key={item.hour}
                      hover
                      selected={isSelected}
                      aria-current={isSelected ? 'time' : undefined}
                      onClick={() => onHourChange?.(item.hour)}
                      tabIndex={0}
                      role="button"
                      aria-label={`+${item.hour} h, ${item.available ? level.toLowerCase() : 'no forecast'}`}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          onHourChange?.(item.hour)
                        }
                      }}
                      sx={{
                        cursor: onHourChange ? 'pointer' : 'default',
                        '&.Mui-selected': { backgroundColor: PALETTE.elevated },
                      }}
                    >
                      <TableCell>+{item.hour} h</TableCell>
                      <TableCell>{clockTime(item.at, timeZone)}</TableCell>
                      <TableCell align="right">
                        {measurement(item.available ? item.weather?.wind_mph : null, 'mph', 0)}
                      </TableCell>
                      <TableCell align="right">
                        {measurement(item.available ? item.weather?.rain_in_hr : null, 'in', 2)}
                      </TableCell>
                      <TableCell align="right">
                        {measurement(item.available ? item.weather?.snow_in_hr : null, 'in', 2)}
                      </TableCell>
                      <TableCell>
                        <RiskChip level={level} />
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        ) : (
          <Typography variant="body2" color="text.secondary">
            Loading the hourly forecast…
          </Typography>
        )}
      </div>
    </Paper>
  )
}

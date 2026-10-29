import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import LinearProgress from '@mui/material/LinearProgress'
import Paper from '@mui/material/Paper'
import Slider from '@mui/material/Slider'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import { useId } from 'react'

import { riskStyle } from '@/theme/risk'
import { PALETTE } from '@/theme/theme'

import { frameLabel } from './frameLabel'
import type { CorridorState } from './useCorridorForecast'
import type { Playback } from './useForecastPlayback'

const MARKS = [0, 12, 24, 36, 48].map((value) => ({
  value,
  label: `+${value} h`,
}))

export interface ForecastTimelineProps {
  corridor: CorridorState
  hour: number
  onHourChange: (hour: number) => void
  playback: Playback
  timeZone?: string | null | undefined
  /** False until an analysis exists; the control is shown disabled. */
  enabled: boolean
}

/**
 * The 0-48 h forecast scrubber.
 *
 * What it changes: which hour's forecast the map band, halos and checkpoint
 * panel show. What it does not change: the trip. The departure, the ETAs,
 * the ranking and the recommendation are computed once by the analysis and
 * this control reads a second view of the same forecast (D28). The caption
 * says so, because a slider labelled "forecast" invites the other reading.
 *
 * The strip under the slider is one cell per frame, coloured by that hour's
 * worst risk anywhere on the route -- a legend-coloured timeline. Hours the
 * provider did not cover are hatched, not hidden, and playback skips them.
 */
export function ForecastTimeline({
  corridor,
  hour,
  onHourChange,
  playback,
  timeZone,
  enabled,
}: ForecastTimelineProps) {
  const labelId = useId()
  const frames = corridor.data?.frames ?? null
  const frame = frames?.find((item) => item.hour === hour) ?? null
  const unavailable = frames ? frames.filter((item) => !item.available).length : 0
  const interactive = enabled && corridor.status === 'ready' && frames !== null

  return (
    <Paper className="flex flex-col gap-3 p-4" aria-labelledby={labelId}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <Typography variant="h2" id={labelId}>
            Forecast timeline
          </Typography>
          <Typography variant="caption" component="p">
            Hours after departure · display only
          </Typography>
        </div>

        <div className="flex items-center gap-1">
          <Tooltip
            title={
              playback.playing
                ? 'Pause'
                : playback.reducedMotion
                  ? 'Play (slowed: reduced motion is on)'
                  : 'Play through the available hours'
            }
          >
            <span>
              <IconButton
                size="small"
                aria-label={playback.playing ? 'Pause playback' : 'Play forecast'}
                aria-pressed={playback.playing}
                onClick={playback.toggle}
                disabled={!interactive}
              >
                {playback.playing ? <PauseIcon /> : <PlayArrowIcon />}
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Back to departure (+0 h)">
            <span>
              <IconButton
                size="small"
                aria-label="Reset to departure"
                onClick={playback.reset}
                disabled={!interactive || (hour === 0 && !playback.playing)}
              >
                <ReplayIcon />
              </IconButton>
            </span>
          </Tooltip>
        </div>
      </div>

      {corridor.status === 'loading' && (
        <div aria-live="polite">
          <LinearProgress aria-label="Loading corridor forecast" />
          <Typography variant="caption" component="p" className="mt-1">
            Loading hourly forecast…
          </Typography>
        </div>
      )}

      {corridor.status === 'error' && (
        <Alert
          severity="warning"
          variant="outlined"
          action={
            <Button color="inherit" size="small" onClick={corridor.retry}>
              Retry
            </Button>
          }
        >
          {corridor.error?.message ?? 'Could not load the corridor forecast.'}
        </Alert>
      )}

      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <Typography variant="body2" aria-live="polite" data-testid="forecast-timestamp">
          <strong>+{hour} h</strong>
          {' · '}
          {interactive ? frameLabel(frame?.at ?? null, timeZone) : '—'}
          {frame && !frame.available && (
            <span className="text-muted"> · no forecast for this hour</span>
          )}
        </Typography>
        {frames && unavailable > 0 && (
          <Typography variant="caption" component="span">
            {unavailable} of {frames.length} hours unavailable
          </Typography>
        )}
      </div>

      <div className="px-1">
        <Slider
          value={hour}
          min={0}
          max={48}
          step={1}
          marks={MARKS}
          disabled={!interactive}
          onChange={(_event, value) => {
            if (typeof value === 'number') onHourChange(value)
          }}
          valueLabelDisplay="auto"
          valueLabelFormat={(value) => `+${value} h`}
          getAriaValueText={(value) =>
            `${value} hours after departure, ${frameLabel(
              frames?.find((item) => item.hour === value)?.at ?? null,
              timeZone,
            )}`
          }
          aria-label="Forecast hour after departure"
          sx={{
            '& .MuiSlider-markLabel': { fontSize: '0.6875rem', color: PALETTE.textSecondary },
            '& .MuiSlider-mark': { height: 8, width: 2 },
          }}
        />

        {/* One cell per frame: the hour's worst level anywhere on the
            route. Hatched = the provider had nothing for that hour. */}
        {frames && (
          <ol
            className="m-0 mt-1 grid list-none gap-px p-0"
            style={{ gridTemplateColumns: `repeat(${frames.length}, minmax(0, 1fr))` }}
            aria-label="Worst risk on the route by hour"
          >
            {frames.map((item) => {
              const style = riskStyle(item.available ? item.summary.max_risk : 'UNKNOWN')
              const isCurrent = item.hour === hour
              return (
                <li
                  key={item.hour}
                  title={`+${item.hour} h: ${item.available ? style.label : 'no forecast'}`}
                  aria-current={isCurrent ? 'time' : undefined}
                  className="h-2 rounded-[2px]"
                  style={{
                    backgroundColor: item.available ? style.color : 'transparent',
                    backgroundImage: item.available
                      ? undefined
                      : `repeating-linear-gradient(45deg, ${style.color} 0 2px, transparent 2px 4px)`,
                    outline: isCurrent ? `2px solid ${PALETTE.textPrimary}` : undefined,
                    outlineOffset: 1,
                  }}
                />
              )
            })}
          </ol>
        )}
      </div>
    </Paper>
  )
}

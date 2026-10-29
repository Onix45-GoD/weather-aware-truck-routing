import Typography from '@mui/material/Typography'

import type { Checkpoint } from '@/api/types'
import { RiskChip } from '@/components/route/RiskChip'
import type { CheckpointHour } from '@/features/corridor/series'
import { frameLabel } from '@/features/corridor/frameLabel'
import { clockTime, measurement } from '@/lib/format'
import { riskStyle } from '@/theme/risk'
import { PALETTE } from '@/theme/theme'

export interface CheckpointPopupProps {
  checkpoint: Checkpoint
  timeZone?: string | null | undefined
  /** This checkpoint across the 49 hours, or null while frames load. */
  series: CheckpointHour[] | null
  /** The timeline's selected hour. */
  hour: number
  onHourChange: (hour: number) => void
}

/**
 * What the map says when a checkpoint is clicked.
 *
 * Two lines a driver needs at a glance — what it is like **when they get
 * there**, and the **48-hour picture** at that spot — and nothing else.
 * The strip is clickable: picking an hour moves the whole timeline, so the
 * popup, the band and the panel never disagree.
 */
export function CheckpointPopup({
  checkpoint,
  timeZone,
  series,
  hour,
  onHourChange,
}: CheckpointPopupProps) {
  const eta = checkpoint.weather
  const selected = series?.find((item) => item.hour === hour) ?? null

  return (
    <div className="flex w-[17rem] flex-col gap-2" data-testid="checkpoint-popup">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Typography variant="body2" component="p" className="font-semibold">
            Checkpoint {checkpoint.index} · mile{' '}
            {checkpoint.distance_from_origin_miles.toFixed(0)}
          </Typography>
          <Typography variant="caption" component="p">
            ETA {clockTime(checkpoint.eta, timeZone)} · this drives the
            recommendation
          </Typography>
        </div>
        <RiskChip level={checkpoint.risk.level} />
      </div>

      <dl className="m-0 grid grid-cols-3 gap-1 text-xs">
        <Measure label="Wind" value={measurement(eta?.wind_mph, 'mph', 0)} />
        <Measure label="Rain" value={measurement(eta?.rain_in_hr, 'in/hr', 2)} />
        <Measure label="Snow" value={measurement(eta?.snow_in_hr, 'in/hr', 2)} />
      </dl>

      <div>
        <Typography variant="caption" component="p" className="mb-1">
          Next 48 h here · click an hour
        </Typography>
        {series ? (
          <ol
            className="m-0 grid list-none gap-px p-0"
            style={{ gridTemplateColumns: `repeat(${series.length}, minmax(0, 1fr))` }}
            aria-label="Risk by hour at this checkpoint"
          >
            {series.map((item) => {
              const level = item.available ? (item.risk?.level ?? 'UNKNOWN') : 'UNKNOWN'
              const style = riskStyle(level)
              const isCurrent = item.hour === hour
              return (
                <li key={item.hour} className="contents">
                  <button
                    type="button"
                    aria-label={`+${item.hour} h: ${item.available ? style.label : 'no forecast'}`}
                    aria-current={isCurrent ? 'time' : undefined}
                    onClick={() => onHourChange(item.hour)}
                    className="h-3 cursor-pointer rounded-[2px] border-0 p-0"
                    style={{
                      backgroundColor: item.available ? style.color : 'transparent',
                      backgroundImage: item.available
                        ? undefined
                        : `repeating-linear-gradient(45deg, ${style.color} 0 2px, transparent 2px 4px)`,
                      outline: isCurrent ? `2px solid ${PALETTE.textPrimary}` : undefined,
                      outlineOffset: 1,
                    }}
                  />
                </li>
              )
            })}
          </ol>
        ) : (
          <Typography variant="caption" component="p" color="text.secondary">
            Loading the hourly forecast…
          </Typography>
        )}
      </div>

      {selected && (
        <div
          className="rounded-md px-2 py-1.5 text-xs"
          style={{ backgroundColor: PALETTE.elevated }}
          data-testid="popup-selected-hour"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold">
              +{selected.hour} h · {frameLabel(selected.at, timeZone)}
            </span>
            {selected.risk && selected.available ? (
              <RiskChip level={selected.risk.level} />
            ) : (
              <RiskChip level="UNKNOWN" />
            )}
          </div>
          {selected.available && selected.weather ? (
            <span className="text-muted">
              {measurement(selected.weather.wind_mph, 'mph', 0)} ·{' '}
              {measurement(selected.weather.rain_in_hr, 'in/hr', 2)} rain ·{' '}
              {measurement(selected.weather.snow_in_hr, 'in/hr', 2)} snow
            </span>
          ) : (
            <span className="text-muted">No forecast for this hour.</span>
          )}
        </div>
      )}
    </div>
  )
}

function Measure({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-md px-2 py-1"
      style={{ backgroundColor: PALETTE.elevated }}
    >
      <dt className="text-[0.6875rem] text-muted">{label}</dt>
      <dd className="m-0 font-semibold tabular-nums">{value}</dd>
    </div>
  )
}

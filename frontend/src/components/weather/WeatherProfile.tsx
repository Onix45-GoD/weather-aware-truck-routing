import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import { useId, useMemo } from 'react'

import type { AnalysedRoute } from '@/api/types'
import { riskColor } from '@/theme/risk'
import { PALETTE } from '@/theme/theme'

const SERIES = [
  { key: 'wind', label: 'Wind (mph)', color: '#60A5FA', max: 70 },
  { key: 'rain', label: 'Rain (in/hr)', color: '#38BDF8', max: 1.0 },
  { key: 'snow', label: 'Snow (in/hr)', color: '#C4B5FD', max: 3.0 },
] as const

export interface WeatherProfileProps {
  route: AnalysedRoute
  selectedIndex: number | null
  onSelect: (index: number) => void
}

/**
 * Conditions along the route, plotted against distance.
 *
 * Every point is a real checkpoint from the analysis — no interpolation
 * between them and no invented hourly series. Checkpoints with no forecast
 * leave a genuine gap in the line rather than being drawn at zero.
 *
 * Hand-rolled SVG rather than a charting library: three polylines and a risk
 * strip do not justify another dependency, and this keeps full control over
 * how missing data is represented.
 */
export function WeatherProfile({
  route,
  selectedIndex,
  onSelect,
}: WeatherProfileProps) {
  const titleId = useId()
  const width = 100
  const height = 46

  const points = useMemo(() => {
    const total = route.metrics.distance_miles || 1
    return route.checkpoints.map((checkpoint) => ({
      index: checkpoint.index,
      x: (checkpoint.distance_from_origin_miles / total) * width,
      mile: checkpoint.distance_from_origin_miles,
      level: checkpoint.risk.level,
      wind: checkpoint.weather?.wind_mph ?? null,
      rain: checkpoint.weather?.rain_in_hr ?? null,
      snow: checkpoint.weather?.snow_in_hr ?? null,
    }))
  }, [route])

  /** Split into runs of consecutive readings, so gaps are not bridged. */
  const paths = useMemo(() => {
    return SERIES.map((series) => {
      const runs: string[] = []
      let current: string[] = []

      for (const point of points) {
        const value = point[series.key]
        if (value === null) {
          if (current.length > 1) runs.push(current.join(' '))
          current = []
          continue
        }
        const y = height - Math.min(1, value / series.max) * (height - 4) - 2
        current.push(`${point.x.toFixed(2)},${y.toFixed(2)}`)
      }
      if (current.length > 1) runs.push(current.join(' '))

      return { ...series, runs }
    })
  }, [points])

  const hasAnyReading = points.some(
    (point) => point.wind !== null || point.rain !== null || point.snow !== null,
  )

  return (
    <Paper className="flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Typography variant="h2" id={titleId}>
          Weather along route
        </Typography>
        <div className="flex flex-wrap gap-3">
          {SERIES.map((series) => (
            <span
              key={series.key}
              className="flex items-center gap-1.5 text-[0.6875rem] text-muted"
            >
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: series.color }}
              />
              {series.label}
            </span>
          ))}
        </div>
      </div>

      {hasAnyReading ? (
        <>
          <svg
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            className="h-32 w-full"
            role="img"
            aria-labelledby={titleId}
          >
            {[0.25, 0.5, 0.75].map((fraction) => (
              <line
                key={fraction}
                x1={0}
                x2={width}
                y1={height * fraction}
                y2={height * fraction}
                stroke={PALETTE.border}
                strokeWidth={0.2}
              />
            ))}

            {paths.map((series) =>
              series.runs.map((run, runIndex) => (
                <polyline
                  key={`${series.key}-${runIndex}`}
                  points={run}
                  fill="none"
                  stroke={series.color}
                  strokeWidth={0.8}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  vectorEffect="non-scaling-stroke"
                />
              )),
            )}

            {selectedIndex !== null &&
              points
                .filter((point) => point.index === selectedIndex)
                .map((point) => (
                  <line
                    key={point.index}
                    x1={point.x}
                    x2={point.x}
                    y1={0}
                    y2={height}
                    stroke={PALETTE.textPrimary}
                    strokeWidth={0.4}
                    strokeDasharray="1 1"
                    vectorEffect="non-scaling-stroke"
                  />
                ))}
          </svg>

          {/* Risk strip: the same colours as the map, read left to right. */}
          <div
            className="flex h-2 w-full overflow-hidden rounded-full"
            role="img"
            aria-label="Risk level along the route"
          >
            {points.slice(0, -1).map((point, pointIndex) => {
              const next = points[pointIndex + 1]
              const span = next ? next.x - point.x : 0
              return (
                <button
                  key={point.index}
                  type="button"
                  onClick={() => onSelect(point.index)}
                  aria-label={`Mile ${point.mile.toFixed(0)}, ${point.level}`}
                  className="h-full border-0 p-0"
                  style={{
                    width: `${(span / width) * 100}%`,
                    backgroundColor: riskColor(point.level),
                    opacity: point.index === selectedIndex ? 1 : 0.75,
                    cursor: 'pointer',
                  }}
                />
              )
            })}
          </div>

          <div className="flex justify-between text-[0.6875rem] text-muted">
            <span>0 mi</span>
            <span>{route.metrics.distance_miles.toFixed(0)} mi</span>
          </div>
        </>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No forecast data was returned for this route, so there is nothing to
          plot. Risk cannot be assessed without it.
        </Typography>
      )}
    </Paper>
  )
}

import type {
  CheckpointRisk,
  CorridorFrame,
  WeatherSample,
} from '@/api/types'

/** One checkpoint at one hour of the corridor forecast. */
export interface CheckpointHour {
  hour: number
  at: string
  /** False when the provider had nothing for this hour (whole route). */
  available: boolean
  weather: WeatherSample | null
  /** Null only when the frame carries no entry for this checkpoint. */
  risk: CheckpointRisk | null
}

/**
 * The 0–48 h series for one checkpoint, pulled out of the frames.
 *
 * Frames are organised by hour (one instant across the route); the panel
 * and the map popup want the other slice — one place across the hours.
 * Same data, re-indexed; nothing is computed or interpolated here.
 */
export function checkpointSeries(
  frames: readonly CorridorFrame[] | null,
  index: number | null,
): CheckpointHour[] | null {
  if (!frames || index === null) return null
  return frames.map((frame) => {
    const point = frame.checkpoints.find((item) => item.index === index) ?? null
    return {
      hour: frame.hour,
      at: frame.at,
      available: frame.available,
      weather: point?.weather ?? null,
      risk: point?.risk ?? null,
    }
  })
}

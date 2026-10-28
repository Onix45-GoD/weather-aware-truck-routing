import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Tooltip from '@mui/material/Tooltip'

import {
  BASEMAP_ORDER,
  BASEMAPS,
  WEATHER_OVERLAYS,
  type BasemapId,
  type WeatherOverlayId,
} from './basemaps'

export interface MapControlsProps {
  basemap: BasemapId
  onBasemapChange: (id: BasemapId) => void
  overlay: WeatherOverlayId | null
  onOverlayChange: (id: WeatherOverlayId | null) => void
  /** False when the server has no OpenWeatherMap key; the group is disabled
   *  with an explanation rather than hidden, so the feature is discoverable. */
  overlaysAvailable: boolean
}

const groupSx = {
  '& .MuiToggleButton-root': {
    px: 1.25,
    py: 0.25,
    fontSize: '0.75rem',
    lineHeight: 1.6,
    textTransform: 'none',
    border: 'none',
  },
} as const

/**
 * Basemap and weather-overlay switches, floating over the map.
 *
 * Both are exclusive toggles. The overlay group allows "nothing selected",
 * which MUI represents as `null` -- the same value the map uses for "no
 * overlay", so no translation is needed.
 */
export function MapControls({
  basemap,
  onBasemapChange,
  overlay,
  onOverlayChange,
  overlaysAvailable,
}: MapControlsProps) {
  const overlayGroup = (
    <ToggleButtonGroup
      exclusive
      size="small"
      aria-label="Weather overlay"
      value={overlay}
      disabled={!overlaysAvailable}
      onChange={(_event, value: WeatherOverlayId | null) =>
        onOverlayChange(value)
      }
      sx={groupSx}
    >
      {WEATHER_OVERLAYS.map((item) => (
        <ToggleButton key={item.id} value={item.id} aria-label={item.label}>
          {item.short}
        </ToggleButton>
      ))}
    </ToggleButtonGroup>
  )

  return (
    <div className="pointer-events-auto absolute right-3 top-3 z-10 flex flex-col items-end gap-2">
      <div className="rounded-lg border border-hairline bg-panel/90 p-0.5 backdrop-blur-sm">
        <ToggleButtonGroup
          exclusive
          size="small"
          aria-label="Basemap"
          value={basemap}
          onChange={(_event, value: BasemapId | null) => {
            // Exclusive groups report null when the active button is clicked
            // again; a basemap cannot be "none", so that click is a no-op.
            if (value) onBasemapChange(value)
          }}
          sx={groupSx}
        >
          {BASEMAP_ORDER.map((id) => (
            <ToggleButton key={id} value={id} aria-label={BASEMAPS[id].label}>
              {BASEMAPS[id].label}
            </ToggleButton>
          ))}
        </ToggleButtonGroup>
      </div>

      <div className="rounded-lg border border-hairline bg-panel/90 p-0.5 backdrop-blur-sm">
        {overlaysAvailable ? (
          overlayGroup
        ) : (
          <Tooltip
            title="Weather overlays need OPENWEATHERMAP_API_KEY on the server"
            placement="left"
          >
            {/* A disabled button fires no pointer events, so the tooltip
                needs a live wrapper to listen on. */}
            <span className="inline-flex">{overlayGroup}</span>
          </Tooltip>
        )}
      </div>
    </div>
  )
}

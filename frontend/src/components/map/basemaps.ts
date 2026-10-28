import { apiBaseUrl } from '@/api/client'

/**
 * Basemap and weather-overlay registries. Pure data, so the map component
 * stays about lifecycle and the choices are testable without WebGL.
 */

export type BasemapId = 'streets' | 'dark'

export interface Basemap {
  label: string
  /** A MapLibre style URL. */
  url: string
}

/**
 * Keyless CARTO basemaps. They are free for reasonable use on condition the
 * attribution stays visible, which `map.css` guarantees.
 *
 * Streets is the default: a driver needs to read road numbers and town
 * names, and risk colours are easier to tell apart on a light ground. Dark
 * remains for low-light cabs and for matching the dashboard.
 */
const CARTO = 'https://basemaps.cartocdn.com/gl'

export const BASEMAPS: Record<BasemapId, Basemap> = {
  streets: { label: 'Streets', url: `${CARTO}/voyager-gl-style/style.json` },
  dark: { label: 'Dark', url: `${CARTO}/dark-matter-gl-style/style.json` },
}

export const DEFAULT_BASEMAP: BasemapId = 'streets'

export const BASEMAP_ORDER: readonly BasemapId[] = ['streets', 'dark']

/**
 * The style URL for a basemap. `VITE_MAP_STYLE_URL` replaces the *default*
 * basemap for deployments that bring their own tiles; the other option is
 * untouched so a user can still switch.
 */
export function basemapStyleUrl(id: BasemapId): string {
  const override = import.meta.env['VITE_MAP_STYLE_URL']
  if (id === DEFAULT_BASEMAP && override) return override
  return BASEMAPS[id].url
}

/** Mirrors the server's allowlist in `providers/openweathermap.py`. */
export type WeatherOverlayId =
  | 'precipitation_new'
  | 'clouds_new'
  | 'wind_new'
  | 'temp_new'

export interface WeatherOverlay {
  id: WeatherOverlayId
  label: string
  /** Short form for the toggle buttons. */
  short: string
}

export const WEATHER_OVERLAYS: readonly WeatherOverlay[] = [
  { id: 'precipitation_new', label: 'Precipitation', short: 'Rain' },
  { id: 'clouds_new', label: 'Clouds', short: 'Clouds' },
  { id: 'wind_new', label: 'Wind speed', short: 'Wind' },
  { id: 'temp_new', label: 'Temperature', short: 'Temp' },
]

export function weatherOverlayLabel(id: WeatherOverlayId): string {
  return WEATHER_OVERLAYS.find((overlay) => overlay.id === id)?.label ?? id
}

/**
 * XYZ template for one overlay. It points at *our* server, which holds the
 * OpenWeatherMap key; the browser never sees a credential. The `{z}/{x}/{y}`
 * placeholders are MapLibre's, substituted per tile.
 */
export function weatherTileUrlTemplate(id: WeatherOverlayId): string {
  return `${apiBaseUrl()}/api/v1/weather-tiles/${id}/{z}/{x}/{y}.png`
}

/** Matches `MAX_TILE_ZOOM` on the server; requests beyond it would be 400s. */
export const WEATHER_TILE_MAX_ZOOM = 12

/**
 * Basemap registry. Pure data, so the map component stays about lifecycle
 * and the choices are testable without WebGL.
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

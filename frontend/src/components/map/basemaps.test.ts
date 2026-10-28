import { describe, expect, it } from 'vitest'

import { apiBaseUrl } from '@/api/client'

import {
  BASEMAP_ORDER,
  BASEMAPS,
  basemapStyleUrl,
  DEFAULT_BASEMAP,
  WEATHER_OVERLAYS,
  weatherOverlayLabel,
  weatherTileUrlTemplate,
} from './basemaps'

describe('basemaps', () => {
  it('defaults to a street map a driver can read', () => {
    expect(DEFAULT_BASEMAP).toBe('streets')
    expect(BASEMAPS.streets.url).toMatch(/voyager/)
  })

  it('offers every registered basemap exactly once', () => {
    expect([...BASEMAP_ORDER].sort()).toEqual(Object.keys(BASEMAPS).sort())
  })

  it('resolves a style URL for each basemap', () => {
    for (const id of BASEMAP_ORDER) {
      expect(basemapStyleUrl(id)).toMatch(/^https:\/\/.+style\.json$/)
    }
  })
})

describe('weather overlays', () => {
  it('requests tiles from our own server, never from OpenWeatherMap', () => {
    const template = weatherTileUrlTemplate('precipitation_new')
    expect(template.startsWith(apiBaseUrl())).toBe(true)
    expect(template).toContain('/api/v1/weather-tiles/precipitation_new/')
    expect(template).toContain('{z}/{x}/{y}.png')
    expect(template).not.toMatch(/openweathermap/)
  })

  it('carries no credential in the tile URL', () => {
    for (const overlay of WEATHER_OVERLAYS) {
      expect(weatherTileUrlTemplate(overlay.id)).not.toMatch(/appid|key=/i)
    }
  })

  it('labels every overlay for the legend', () => {
    for (const overlay of WEATHER_OVERLAYS) {
      expect(weatherOverlayLabel(overlay.id)).toBe(overlay.label)
    }
  })
})

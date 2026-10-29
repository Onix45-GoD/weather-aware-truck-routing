import { describe, expect, it } from 'vitest'

import { BASEMAP_ORDER, BASEMAPS, basemapStyleUrl, DEFAULT_BASEMAP } from './basemaps'

describe('basemaps', () => {
  it('defaults to a street map a driver can read', () => {
    expect(DEFAULT_BASEMAP).toBe('streets')
    expect(BASEMAPS.streets.url).toMatch(/voyager/)
  })

  it('offers every registered basemap exactly once', () => {
    expect([...BASEMAP_ORDER].sort()).toEqual(Object.keys(BASEMAPS).sort())
  })

  it('resolves a keyless style URL for each basemap', () => {
    for (const id of BASEMAP_ORDER) {
      expect(basemapStyleUrl(id)).toMatch(/^https:\/\/.+style\.json$/)
      expect(basemapStyleUrl(id)).not.toMatch(/key=|token=/i)
    }
  })
})

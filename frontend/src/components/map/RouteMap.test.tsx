/**
 * Map lifecycle: creation, cleanup, and failure.
 *
 * jsdom has no WebGL, so `maplibre-gl` itself is mocked here. These tests are
 * about the *lifecycle* the component owns — one instance, listeners removed,
 * `remove()` on unmount, a usable fallback when the basemap fails. The
 * GeoJSON building is pure and tested separately without any mock.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RiskLevel } from '@/api/types'
import { Providers } from '@/app/Providers'
import { makeRoutes } from '@/test/fixtures'

const mapInstances = vi.hoisted(() => [] as Array<Record<string, unknown>>)
const popupInstances = vi.hoisted(() => [] as Array<Record<string, unknown>>)

vi.mock('maplibre-gl', () => {
  class FakeMap {
    handlers = new Map<string, Set<(event: unknown) => void>>()
    removed = false
    sources = new Set<string>()
    layers = new Set<string>()
    styleUrl: string
    sourceSpecs = new Map<string, Record<string, unknown>>()

    options: Record<string, unknown>

    constructor(options: Record<string, unknown>) {
      this.options = options
      this.styleUrl = String(options['style'])
      mapInstances.push(this as unknown as Record<string, unknown>)
    }

    on(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = (maybeHandler ?? layerOrHandler) as (e: unknown) => void
      const key =
        typeof layerOrHandler === 'string' ? `${event}:${layerOrHandler}` : event
      if (!this.handlers.has(key)) this.handlers.set(key, new Set())
      this.handlers.get(key)!.add(handler)
      if (event === 'style.load') queueMicrotask(() => handler({}))
    }

    off(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = (maybeHandler ?? layerOrHandler) as (e: unknown) => void
      const key =
        typeof layerOrHandler === 'string' ? `${event}:${layerOrHandler}` : event
      this.handlers.get(key)?.delete(handler)
    }

    emit(key: string, payload: unknown) {
      this.handlers.get(key)?.forEach((handler) => handler(payload))
    }

    addControl() {}
    addSource(id: string, spec: Record<string, unknown>) {
      this.sources.add(id)
      this.sourceSpecs.set(id, spec)
    }
    removeSource(id: string) {
      this.sources.delete(id)
      this.sourceSpecs.delete(id)
    }
    removeLayer(id: string) {
      this.layers.delete(id)
    }
    /** A new style discards every source and layer, then loads. */
    setStyle(url: string) {
      this.styleUrl = url
      this.sources.clear()
      this.sourceSpecs.clear()
      this.layers.clear()
      queueMicrotask(() => this.emit('style.load', {}))
    }
    addLayer(layer: { id: string }) {
      this.layers.add(layer.id)
    }
    getSource(id: string) {
      return this.sources.has(id) ? { setData: vi.fn() } : undefined
    }
    getLayer(id: string) {
      return this.layers.has(id) ? { id } : undefined
    }
    setFilter() {}
    setPaintProperty() {}
    fitBounds() {}
    getCanvas() {
      return { style: {} as CSSStyleDeclaration }
    }
    remove() {
      this.removed = true
      this.handlers.clear()
    }

    /** Count of registered handlers, for leak assertions. */
    get handlerCount() {
      let total = 0
      for (const set of this.handlers.values()) total += set.size
      return total
    }
  }

  class FakePopup {
    lngLat: unknown = null
    node: HTMLElement | null = null
    added = false
    handlers = new Map<string, Set<() => void>>()
    setLngLat(lngLat: unknown) {
      this.lngLat = lngLat
      return this
    }
    setDOMContent(node: HTMLElement) {
      this.node = node
      return this
    }
    addTo() {
      this.added = true
      if (!popupInstances.includes(this as unknown as Record<string, unknown>)) {
        popupInstances.push(this as unknown as Record<string, unknown>)
      }
      return this
    }
    on(event: string, handler: () => void) {
      if (!this.handlers.has(event)) this.handlers.set(event, new Set())
      this.handlers.get(event)!.add(handler)
    }
    remove() {
      this.added = false
      this.handlers.get('close')?.forEach((h) => h())
    }
  }

  return {
    Map: FakeMap,
    NavigationControl: class {},
    ScaleControl: class {},
    Popup: FakePopup,
  }
})

const { RouteMap } = await import('./RouteMap')

function renderMap(props: Partial<Parameters<typeof RouteMap>[0]> = {}) {
  return render(
    <Providers>
      <div style={{ height: 400 }}>
        <RouteMap
          routes={makeRoutes(2)}
          selectedRouteId="tomtom-0"
          selectedCheckpointIndex={null}
          onSelectRoute={vi.fn()}
          onSelectCheckpoint={vi.fn()}
          origin={{ latitude: 39.7, longitude: -104.9, label: 'Denver' }}
          destination={{ latitude: 41.8, longitude: -87.6, label: 'Chicago' }}
          {...props}
        />
      </div>
    </Providers>,
  )
}

beforeEach(() => {
  mapInstances.length = 0
  popupInstances.length = 0
})

describe('map lifecycle', () => {
  it('creates exactly one map instance', async () => {
    renderMap()
    await waitFor(() => expect(mapInstances).toHaveLength(1))
  })

  it('does not create a second map when props change', async () => {
    const { rerender } = renderMap()
    await waitFor(() => expect(mapInstances).toHaveLength(1))

    rerender(
      <Providers>
        <div style={{ height: 400 }}>
          <RouteMap
            routes={makeRoutes(3)}
            selectedRouteId="tomtom-1"
            selectedCheckpointIndex={2}
            onSelectRoute={vi.fn()}
            onSelectCheckpoint={vi.fn()}
          />
        </div>
      </Providers>,
    )

    expect(mapInstances).toHaveLength(1)
  })

  it('destroys the map and its listeners on unmount', async () => {
    const { unmount } = renderMap()
    await waitFor(() => expect(mapInstances).toHaveLength(1))

    const map = mapInstances[0] as unknown as {
      removed: boolean
      handlerCount: number
    }
    unmount()

    expect(map.removed).toBe(true)
    expect(map.handlerCount).toBe(0)
  })

  it('adds the sources and layers it draws with', async () => {
    renderMap()
    const map = await waitFor(() => {
      expect(mapInstances).toHaveLength(1)
      return mapInstances[0] as unknown as { sources: Set<string> }
    })

    await waitFor(() => expect(map.sources.size).toBeGreaterThan(0))
    expect(map.sources.has('routes')).toBe(true)
    expect(map.sources.has('checkpoints')).toBe(true)
  })
})

describe('map failure', () => {
  it('shows a fallback and keeps the rest of the page usable', async () => {
    renderMap()
    const map = await waitFor(() => {
      expect(mapInstances).toHaveLength(1)
      return mapInstances[0] as unknown as {
        emit: (key: string, payload: unknown) => void
      }
    })

    map.emit('error', { error: { message: 'Failed to load style' } })

    expect(await screen.findByText(/map unavailable/i)).toBeVisible()
    expect(
      screen.getByText(/route analysis below is unaffected/i),
    ).toBeVisible()
  })

  it('ignores a tile error that is not fatal', async () => {
    renderMap()
    const map = await waitFor(() => {
      expect(mapInstances).toHaveLength(1)
      return mapInstances[0] as unknown as {
        emit: (key: string, payload: unknown) => void
      }
    })

    map.emit('error', { error: { message: 'tile 404' } })

    expect(screen.queryByText(/map unavailable/i)).not.toBeInTheDocument()
  })
})

describe('map accessibility', () => {
  it('exposes the container with a descriptive name', () => {
    renderMap()
    expect(
      screen.getByRole('application', { name: /route map/i }),
    ).toBeInTheDocument()
  })

  it('renders the risk legend', () => {
    renderMap()
    expect(screen.getByText('Weather risk')).toBeVisible()
    expect(screen.getByText('No Travel')).toBeVisible()
    expect(screen.getByText('No data')).toBeVisible()
  })

  it('prompts when no route is selected', () => {
    renderMap({ selectedRouteId: null })
    expect(screen.getByText(/select a route to see/i)).toBeVisible()
  })
})

type Fake = {
  styleUrl: string
  sources: Set<string>
  layers: Set<string>
  sourceSpecs: Map<string, Record<string, unknown>>
}

async function mountedMap(
  props: Partial<Parameters<typeof RouteMap>[0]> = {},
): Promise<Fake> {
  renderMap(props)
  const map = await waitFor(() => {
    expect(mapInstances).toHaveLength(1)
    return mapInstances[0] as unknown as Fake
  })
  await waitFor(() => expect(map.layers.has('route-line')).toBe(true))
  return map
}

describe('basemap switching', () => {
  it('starts on the street map', async () => {
    const map = await mountedMap()
    expect(map.styleUrl).toMatch(/voyager/)
    expect(screen.getByRole('button', { name: 'Streets' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('replaces the style and redraws the routes on top of it', async () => {
    const map = await mountedMap()
    const user = userEvent.setup()

    await user.click(screen.getByRole('button', { name: 'Dark' }))

    await waitFor(() => expect(map.styleUrl).toMatch(/dark-matter/))
    // The new style wiped every layer; they must come back by themselves.
    await waitFor(() => expect(map.layers.has('route-line')).toBe(true))
    expect(map.sources.has('routes')).toBe(true)
    expect(map.sources.has('checkpoints')).toBe(true)
  })

  it('does not recreate the map to change the style', async () => {
    await mountedMap()
    await userEvent.setup().click(screen.getByRole('button', { name: 'Dark' }))
    expect(mapInstances).toHaveLength(1)
  })
})

describe('corridor forecast layers', () => {
  const levels = new Map<number, RiskLevel>([
    [0, 'LOW'],
    [1, 'SEVERE'],
  ])

  it('adds the band and halo layers under the route layers', async () => {
    const map = await mountedMap({ corridorLevels: levels, corridorLabel: '+12 h · Fri 6:00 PM MST' })
    expect(map.layers.has('corridor-band')).toBe(true)
    expect(map.layers.has('corridor-halo')).toBe(true)
    expect(map.sources.has('corridor-band')).toBe(true)
    expect(map.sources.has('corridor-halo')).toBe(true)
  })

  it('shows which hour the band represents', async () => {
    await mountedMap({ corridorLevels: levels, corridorLabel: '+12 h · Fri 6:00 PM MST' })
    expect(screen.getByTestId('corridor-badge')).toHaveTextContent('+12 h · Fri 6:00 PM MST')
    expect(screen.getByText(/wide band & halos/i)).toBeVisible()
  })

  it('draws no band and no badge without a frame', async () => {
    await mountedMap({ corridorLevels: null, corridorLabel: null })
    expect(screen.queryByTestId('corridor-badge')).not.toBeInTheDocument()
    expect(screen.queryByText(/wide band & halos/i)).not.toBeInTheDocument()
  })

  it('writes the frame to the sources without recreating the map', async () => {
    const { rerender } = renderMap({ corridorLevels: null })
    await waitFor(() => expect(mapInstances).toHaveLength(1))
    rerender(
      <Providers>
        <div style={{ height: 400 }}>
          <RouteMap
            routes={makeRoutes(2)}
            selectedRouteId="tomtom-0"
            selectedCheckpointIndex={null}
            onSelectRoute={vi.fn()}
            onSelectCheckpoint={vi.fn()}
            corridorLevels={levels}
            corridorLabel="+3 h"
          />
        </div>
      </Providers>,
    )
    expect(mapInstances).toHaveLength(1)
    expect(screen.getByTestId('corridor-badge')).toHaveTextContent('+3 h')
  })
})

describe('checkpoint popup', () => {
  const point = makeRoutes(1)[0]!.checkpoints[1]!

  it('anchors a popup at the checkpoint and renders the content inside it', async () => {
    await mountedMap({
      popup: { checkpoint: point, content: <div data-testid="popup-body">Weather here</div> },
    })
    await waitFor(() => expect(popupInstances).toHaveLength(1))
    const popup = popupInstances[0] as unknown as { lngLat: [number, number]; node: HTMLElement; added: boolean }
    expect(popup.lngLat).toEqual([point.longitude, point.latitude])
    expect(popup.added).toBe(true)
    expect(popup.node.querySelector('[data-testid="popup-body"]')?.textContent).toBe('Weather here')
  })

  it('clears the selection when the user closes the popup', async () => {
    const onSelectCheckpoint = vi.fn()
    await mountedMap({ onSelectCheckpoint, popup: { checkpoint: point, content: <span>x</span> } })
    await waitFor(() => expect(popupInstances).toHaveLength(1))
    const popup = popupInstances[0] as unknown as { handlers: Map<string, Set<() => void>> }
    popup.handlers.get('close')!.forEach((h) => h())
    expect(onSelectCheckpoint).toHaveBeenCalledWith(null)
  })

  it('removes the popup without bouncing a dismissal when the selection is cleared', async () => {
    const onSelectCheckpoint = vi.fn()
    const { rerender } = renderMap({ onSelectCheckpoint, popup: { checkpoint: point, content: <span>x</span> } })
    await waitFor(() => expect(popupInstances).toHaveLength(1))
    rerender(
      <Providers>
        <div style={{ height: 400 }}>
          <RouteMap
            routes={makeRoutes(2)}
            selectedRouteId="tomtom-0"
            selectedCheckpointIndex={null}
            onSelectRoute={vi.fn()}
            onSelectCheckpoint={onSelectCheckpoint}
            popup={null}
          />
        </div>
      </Providers>,
    )
    const popup = popupInstances[0] as unknown as { added: boolean }
    expect(popup.added).toBe(false)
    expect(onSelectCheckpoint).not.toHaveBeenCalled()
  })
})

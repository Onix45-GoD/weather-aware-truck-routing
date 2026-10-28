/**
 * Map lifecycle: creation, cleanup, and failure.
 *
 * jsdom has no WebGL, so `maplibre-gl` itself is mocked here. These tests are
 * about the *lifecycle* the component owns — one instance, listeners removed,
 * `remove()` on unmount, a usable fallback when the basemap fails. The
 * GeoJSON building is pure and tested separately without any mock.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { Providers } from '@/app/Providers'
import { makeRoutes } from '@/test/fixtures'

const mapInstances = vi.hoisted(() => [] as Array<Record<string, unknown>>)

vi.mock('maplibre-gl', () => {
  class FakeMap {
    handlers = new Map<string, Set<(event: unknown) => void>>()
    removed = false
    sources = new Set<string>()
    layers = new Set<string>()

    options: Record<string, unknown>

    constructor(options: Record<string, unknown>) {
      this.options = options
      mapInstances.push(this as unknown as Record<string, unknown>)
    }

    on(event: string, layerOrHandler: unknown, maybeHandler?: unknown) {
      const handler = (maybeHandler ?? layerOrHandler) as (e: unknown) => void
      const key =
        typeof layerOrHandler === 'string' ? `${event}:${layerOrHandler}` : event
      if (!this.handlers.has(key)) this.handlers.set(key, new Set())
      this.handlers.get(key)!.add(handler)
      if (event === 'load') queueMicrotask(() => handler({}))
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
    addSource(id: string) {
      this.sources.add(id)
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

  return {
    Map: FakeMap,
    NavigationControl: class {},
    ScaleControl: class {},
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

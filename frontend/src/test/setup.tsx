import '@testing-library/jest-dom/vitest'

import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// jsdom has no WebGL, so a real MapLibre instance cannot be constructed.
// The map is mocked at the module boundary; `geojson.ts` -- the part with
// actual logic -- is pure and tested directly without any mock.
vi.mock('@/components/map/LazyRouteMap', () => ({
  LazyRouteMap: (props: { routes: unknown[]; selectedRouteId: string | null }) => (
    <div
      data-testid="map-container"
      data-route-count={props.routes.length}
      data-selected-route={props.selectedRouteId ?? ''}
    />
  ),
}))

// jsdom implements neither of these, and MUI reads both.
if (!window.matchMedia) {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as typeof window.matchMedia
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver
}

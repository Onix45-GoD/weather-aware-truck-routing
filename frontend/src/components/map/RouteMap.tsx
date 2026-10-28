import Alert from '@mui/material/Alert'
import AlertTitle from '@mui/material/AlertTitle'
import {
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type MapLayerMouseEvent,
} from 'maplibre-gl'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { AnalysedRoute } from '@/api/types'
import { riskColor, RISK_ORDER, riskStyle } from '@/theme/risk'

import {
  basemapStyleUrl,
  DEFAULT_BASEMAP,
  WEATHER_TILE_MAX_ZOOM,
  weatherOverlayLabel,
  weatherTileUrlTemplate,
  type BasemapId,
  type WeatherOverlayId,
} from './basemaps'
import {
  checkpointPoints,
  riskSegments,
  routeLines,
  routesBounds,
} from './geojson'
import { MapControls } from './MapControls'
import '@/styles/map.css'

const SOURCES = {
  routes: 'routes',
  risk: 'risk-segments',
  checkpoints: 'checkpoints',
  endpoints: 'endpoints',
  weather: 'weather-overlay',
} as const

const LAYERS = {
  weather: 'weather-overlay',
  routeCasing: 'route-casing',
  routeLine: 'route-line',
  riskLine: 'risk-line',
  checkpointDots: 'checkpoint-dots',
  checkpointSelected: 'checkpoint-selected',
  endpointDots: 'endpoint-dots',
} as const

const EMPTY = { type: 'FeatureCollection' as const, features: [] }

/** Narrow `getSource` to a GeoJSON source before writing to it. */
function setSourceData(map: MapLibreMap, id: string, data: unknown): void {
  const source = map.getSource(id) as GeoJSONSource | undefined
  source?.setData(data as Parameters<GeoJSONSource['setData']>[0])
}

/** Colour-by-risk expression. A factory, because MapLibre mutates nothing
 *  but its types demand mutable arrays, and `as const` would freeze them. */
function riskColorExpression(): ExpressionSpecification {
  return [
    'match',
    ['get', 'level'],
    'LOW', riskColor('LOW'),
    'MODERATE', riskColor('MODERATE'),
    'HIGH', riskColor('HIGH'),
    'SEVERE', riskColor('SEVERE'),
    'NO_TRAVEL', riskColor('NO_TRAVEL'),
    riskColor('UNKNOWN'),
  ]
}

type Place = { latitude: number; longitude: number; label: string }

export interface RouteMapProps {
  routes: AnalysedRoute[]
  selectedRouteId: string | null
  selectedCheckpointIndex: number | null
  onSelectRoute: (routeId: string) => void
  onSelectCheckpoint: (index: number) => void
  origin?: Place | null | undefined
  destination?: Place | null | undefined
  /** Whether the server can serve OpenWeatherMap tiles. Defaults to no. */
  weatherOverlaysAvailable?: boolean | undefined
}

/**
 * Write every data source for the current props.
 *
 * Separated from the effect so one `try` covers all four writes. Any
 * MapLibre failure in here must surface *on the map* and nowhere else: an
 * uncaught throw inside an effect unmounts the whole application, which
 * turns a finished analysis into a blank page and loses the message in the
 * console.
 */
function pushData(
  map: MapLibreMap,
  routes: AnalysedRoute[],
  selectedRouteId: string | null,
  selectedRoute: AnalysedRoute | null,
  origin: Place | null | undefined,
  destination: Place | null | undefined,
): void {
  const lines = routeLines(routes)
  setSourceData(map, SOURCES.routes, {
    ...lines,
    features: lines.features.map((feature) => ({
      ...feature,
      properties: {
        ...feature.properties,
        isSelected: feature.properties.routeId === selectedRouteId,
      },
    })),
  })

  setSourceData(
    map,
    SOURCES.risk,
    selectedRoute ? riskSegments(selectedRoute) : EMPTY,
  )
  setSourceData(
    map,
    SOURCES.checkpoints,
    selectedRoute ? checkpointPoints(selectedRoute) : EMPTY,
  )

  const endpoints = []
  if (origin) {
    endpoints.push({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [origin.longitude, origin.latitude],
      },
      properties: { isOrigin: true, label: origin.label },
    })
  }
  if (destination) {
    endpoints.push({
      type: 'Feature' as const,
      geometry: {
        type: 'Point' as const,
        coordinates: [destination.longitude, destination.latitude],
      },
      properties: { isOrigin: false, label: destination.label },
    })
  }
  setSourceData(map, SOURCES.endpoints, {
    type: 'FeatureCollection',
    features: endpoints,
  })
}

/**
 * Add the route sources and layers. Idempotent, because it runs after every
 * style load: switching basemaps replaces the whole style, which discards
 * every source and layer we added, so they are simply added again.
 */
function addRouteLayers(map: MapLibreMap): void {
  for (const id of [
    SOURCES.routes,
    SOURCES.risk,
    SOURCES.checkpoints,
    SOURCES.endpoints,
  ]) {
    if (!map.getSource(id)) {
      map.addSource(id, { type: 'geojson', data: EMPTY })
    }
  }

  if (!map.getLayer(LAYERS.routeCasing)) {
    map.addLayer({
      id: LAYERS.routeCasing,
      type: 'line',
      source: SOURCES.routes,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': '#060B14',
        'line-width': ['case', ['get', 'isSelected'], 9, 6],
        'line-opacity': 0.9,
      },
    })
  }

  if (!map.getLayer(LAYERS.routeLine)) {
    map.addLayer({
      id: LAYERS.routeLine,
      type: 'line',
      source: SOURCES.routes,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        // Unselected alternatives stay visible but recede. Ineligible ones
        // take the No-Travel colour so "blocked" reads differently from
        // "not chosen".
        'line-color': [
          'case',
          ['get', 'isSelected'],
          '#3B82F6',
          ['!', ['get', 'eligible']],
          '#A855F7',
          '#64748B',
        ],
        'line-width': ['case', ['get', 'isSelected'], 5, 3],
        'line-opacity': ['case', ['get', 'isSelected'], 0.35, 0.75],
      },
    })
  }

  // Risk colouring sits above the plain line and only covers the selected
  // route -- three routes of risk colour at once is unreadable.
  if (!map.getLayer(LAYERS.riskLine)) {
    map.addLayer({
      id: LAYERS.riskLine,
      type: 'line',
      source: SOURCES.risk,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': riskColorExpression(),
        'line-width': 5,
        'line-opacity': 0.95,
      },
    })
  }

  if (!map.getLayer(LAYERS.checkpointDots)) {
    map.addLayer({
      id: LAYERS.checkpointDots,
      type: 'circle',
      source: SOURCES.checkpoints,
      paint: {
        'circle-radius': 4,
        'circle-color': riskColorExpression(),
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#08111F',
      },
    })
  }

  if (!map.getLayer(LAYERS.checkpointSelected)) {
    map.addLayer({
      id: LAYERS.checkpointSelected,
      type: 'circle',
      source: SOURCES.checkpoints,
      filter: ['==', ['get', 'index'], -1],
      paint: {
        'circle-radius': 8,
        'circle-color': 'rgba(0,0,0,0)',
        'circle-stroke-width': 2.5,
        'circle-stroke-color': '#F1F5F9',
      },
    })
  }

  if (!map.getLayer(LAYERS.endpointDots)) {
    map.addLayer({
      id: LAYERS.endpointDots,
      type: 'circle',
      source: SOURCES.endpoints,
      paint: {
        'circle-radius': 7,
        'circle-color': ['case', ['get', 'isOrigin'], '#22C55E', '#F1F5F9'],
        'circle-stroke-width': 2,
        'circle-stroke-color': '#08111F',
      },
    })
  }
}

/**
 * Replace the weather raster with `overlay`, or remove it when null.
 *
 * The raster goes *under* the route casing so the recommendation is never
 * obscured by a rain cell. Tiles come from our own server, which holds the
 * OpenWeatherMap key -- see `weatherTileUrlTemplate`.
 */
function setWeatherOverlay(
  map: MapLibreMap,
  overlay: WeatherOverlayId | null,
): void {
  if (map.getLayer(LAYERS.weather)) map.removeLayer(LAYERS.weather)
  if (map.getSource(SOURCES.weather)) map.removeSource(SOURCES.weather)
  if (!overlay) return

  map.addSource(SOURCES.weather, {
    type: 'raster',
    tiles: [weatherTileUrlTemplate(overlay)],
    tileSize: 256,
    maxzoom: WEATHER_TILE_MAX_ZOOM,
    attribution: 'Weather © OpenWeatherMap',
  })
  map.addLayer(
    {
      id: LAYERS.weather,
      type: 'raster',
      source: SOURCES.weather,
      paint: { 'raster-opacity': 0.7 },
    },
    map.getLayer(LAYERS.routeCasing) ? LAYERS.routeCasing : undefined,
  )
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

export function RouteMap({
  routes,
  selectedRouteId,
  selectedCheckpointIndex,
  onSelectRoute,
  onSelectCheckpoint,
  origin,
  destination,
  weatherOverlaysAvailable = false,
}: RouteMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  // Counts style loads. Zero means "no style yet"; it increments on the
  // first load and again after every basemap switch, so effects that draw
  // on the style re-run exactly when the style is replaced.
  const [styleGeneration, setStyleGeneration] = useState(0)
  const [styleError, setStyleError] = useState<string | null>(null)
  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP)
  const [overlay, setOverlay] = useState<WeatherOverlayId | null>(null)
  const ready = styleGeneration > 0

  // Latest callbacks, so map handlers registered once never close over stale
  // props. Re-registering them on every render would leak listeners.
  //
  // Updated in an effect rather than during render: writing a ref while
  // rendering is unsafe under concurrent rendering, and the effect runs
  // before any user interaction can fire a map event.
  const handlers = useRef({ onSelectRoute, onSelectCheckpoint })
  useEffect(() => {
    handlers.current = { onSelectRoute, onSelectCheckpoint }
  })

  const selectedRoute = useMemo(
    () => routes.find((route) => route.route_id === selectedRouteId) ?? null,
    [routes, selectedRouteId],
  )

  // --- lifecycle: create exactly one map, destroy it on unmount -----------
  useEffect(() => {
    const container = containerRef.current
    if (!container || mapRef.current) return

    let map: MapLibreMap
    try {
      map = new MapLibreMap({
        container,
        style: basemapStyleUrl(DEFAULT_BASEMAP),
        center: [-96.5, 40.5],
        zoom: 3.6,
        attributionControl: { compact: true },
      })
    } catch (error) {
      // WebGL unavailable (headless browser, blocked GPU, jsdom). This is
      // the case the set-state-in-effect rule exempts: reporting the result
      // of synchronising with an external system. It cannot be derived
      // during render, because it is only knowable by trying.
      // oxlint-disable-next-line react/set-state-in-effect
      setStyleError(describe(error) || 'This browser could not initialise the map.')
      return
    }

    mapRef.current = map
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right')
    map.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-left')

    // `style.load` rather than `load`: `load` fires once, `style.load` fires
    // for every style, which is what a basemap switch needs.
    const onStyleLoad = () => {
      setStyleError(null)
      setStyleGeneration((generation) => generation + 1)
    }
    const onError = (event: { error?: { message?: string } }) => {
      // Tile 404s are noisy but not fatal; a style failure is.
      const message = event.error?.message ?? ''
      if (/style|sprite|glyphs/i.test(message)) {
        setStyleError(
          'The map basemap could not be loaded. Route analysis below is ' +
            'unaffected.',
        )
      }
    }

    map.on('style.load', onStyleLoad)
    map.on('error', onError)

    return () => {
      map.off('style.load', onStyleLoad)
      map.off('error', onError)
      map.remove()
      mapRef.current = null
      setStyleGeneration(0)
    }
  }, [])

  // --- basemap switch ------------------------------------------------------
  // The map is created with the default, so the first run is a no-op; later
  // runs replace the style, and `style.load` re-triggers the layer effects.
  const appliedBasemap = useRef<BasemapId>(DEFAULT_BASEMAP)
  useEffect(() => {
    const map = mapRef.current
    if (!map || appliedBasemap.current === basemap) return
    appliedBasemap.current = basemap
    map.setStyle(basemapStyleUrl(basemap))
  }, [basemap])

  // --- sources and layers, (re)created on every style load ---------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    try {
      addRouteLayers(map)
    } catch (error) {
      // oxlint-disable-next-line react/set-state-in-effect
      setStyleError(`Could not prepare the map layers: ${describe(error)}`)
      return
    }

    const clickRoute = (event: MapLayerMouseEvent) => {
      const routeId = event.features?.[0]?.properties?.['routeId']
      if (typeof routeId === 'string') handlers.current.onSelectRoute(routeId)
    }
    const clickCheckpoint = (event: MapLayerMouseEvent) => {
      const index = event.features?.[0]?.properties?.['index']
      if (typeof index === 'number') handlers.current.onSelectCheckpoint(index)
    }
    const enter = () => {
      map.getCanvas().style.cursor = 'pointer'
    }
    const leave = () => {
      map.getCanvas().style.cursor = ''
    }

    map.on('click', LAYERS.routeLine, clickRoute)
    map.on('click', LAYERS.checkpointDots, clickCheckpoint)
    for (const layer of [LAYERS.routeLine, LAYERS.checkpointDots]) {
      map.on('mouseenter', layer, enter)
      map.on('mouseleave', layer, leave)
    }

    return () => {
      map.off('click', LAYERS.routeLine, clickRoute)
      map.off('click', LAYERS.checkpointDots, clickCheckpoint)
      for (const layer of [LAYERS.routeLine, LAYERS.checkpointDots]) {
        map.off('mouseenter', layer, enter)
        map.off('mouseleave', layer, leave)
      }
    }
  }, [ready, styleGeneration])

  // --- weather overlay -----------------------------------------------------
  // Depends on the generation too: a basemap switch wipes the raster with
  // everything else, so it is re-added after the route layers exist.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    try {
      setWeatherOverlay(map, weatherOverlaysAvailable ? overlay : null)
    } catch (error) {
      // oxlint-disable-next-line react/set-state-in-effect
      setStyleError(`Could not show the weather overlay: ${describe(error)}`)
    }
  }, [ready, styleGeneration, overlay, weatherOverlaysAvailable])

  // --- data updates -------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    try {
      pushData(map, routes, selectedRouteId, selectedRoute, origin, destination)
    } catch (error) {
      // External-system failure (MapLibre rejected the data); same exemption
      // as the constructor catch above. Only knowable by trying.
      // oxlint-disable-next-line react/set-state-in-effect
      setStyleError(`Could not draw the routes: ${describe(error)}`)
    }
  }, [
    ready,
    styleGeneration,
    routes,
    selectedRouteId,
    selectedRoute,
    origin,
    destination,
  ])

  // Highlight ring follows the selected checkpoint.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !map.getLayer(LAYERS.checkpointSelected)) return
    map.setFilter(LAYERS.checkpointSelected, [
      '==',
      ['get', 'index'],
      selectedCheckpointIndex ?? -1,
    ])
  }, [ready, styleGeneration, selectedCheckpointIndex])

  // Fit to the routes once they change, not on every render.
  const fittedKey = useRef<string>('')
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || routes.length === 0) return

    const key = routes.map((route) => route.route_id).join('|')
    if (key === fittedKey.current) return
    fittedKey.current = key

    const bounds = routesBounds(routes)
    if (!bounds) return
    try {
      map.fitBounds(bounds, { padding: 56, duration: 650, maxZoom: 9 })
    } catch (error) {
      // oxlint-disable-next-line react/set-state-in-effect
      setStyleError(`Could not frame the routes: ${describe(error)}`)
    }
  }, [ready, routes])

  return (
    <div className="relative h-full w-full min-w-0 overflow-hidden rounded-xl border border-hairline">
      <div
        ref={containerRef}
        data-testid="map-container"
        role="application"
        aria-label="Route map with weather risk overlay"
        className="absolute inset-0"
      />

      {styleError && (
        <div className="absolute inset-x-3 top-3 z-10">
          <Alert severity="warning" variant="filled">
            <AlertTitle>Map unavailable</AlertTitle>
            {styleError}
          </Alert>
        </div>
      )}

      <MapControls
        basemap={basemap}
        onBasemapChange={setBasemap}
        overlay={overlay}
        onOverlayChange={setOverlay}
        overlaysAvailable={weatherOverlaysAvailable}
      />

      <MapLegend
        hasSelection={Boolean(selectedRoute)}
        overlay={weatherOverlaysAvailable ? overlay : null}
      />
    </div>
  )
}

function MapLegend({
  hasSelection,
  overlay,
}: {
  hasSelection: boolean
  overlay: WeatherOverlayId | null
}) {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 z-10 rounded-lg border border-hairline bg-panel/90 p-3 backdrop-blur-sm">
      <p className="m-0 mb-2 text-xs font-semibold text-ink">Weather risk</p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0">
        {RISK_ORDER.map((level) => (
          <li key={level} className="flex items-center gap-2 text-xs text-muted">
            <span
              aria-hidden
              className="h-2.5 w-2.5 rounded-full"
              style={{ backgroundColor: riskStyle(level).color }}
            />
            {riskStyle(level).label}
          </li>
        ))}
        <li className="flex items-center gap-2 text-xs text-muted">
          <span
            aria-hidden
            className="h-2.5 w-2.5 rounded-full"
            style={{ backgroundColor: riskStyle('UNKNOWN').color }}
          />
          {riskStyle('UNKNOWN').label}
        </li>
      </ul>
      {!hasSelection && (
        <p className="m-0 mt-2 max-w-[13rem] text-[0.6875rem] leading-snug text-muted">
          Select a route to see its checkpoints and risk colouring.
        </p>
      )}
      {overlay && (
        // "Now" is load-bearing. The overlay is current conditions; the
        // route colours are the forecast at each ETA. They are not the same
        // thing, and the legend must not let them be read as one.
        <p className="m-0 mt-2 max-w-[13rem] text-[0.6875rem] leading-snug text-muted">
          Overlay: {weatherOverlayLabel(overlay)} <strong>now</strong>, not at
          ETA. Route colours are the forecast.
        </p>
      )}
    </div>
  )
}

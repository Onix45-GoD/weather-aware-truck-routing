import Alert from '@mui/material/Alert'
import AlertTitle from '@mui/material/AlertTitle'
import {
  Map as MapLibreMap,
  NavigationControl,
  Popup,
  ScaleControl,
  type ExpressionSpecification,
  type GeoJSONSource,
  type MapLayerMouseEvent,
} from 'maplibre-gl'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import type { AnalysedRoute, Checkpoint } from '@/api/types'
import { riskColor, RISK_ORDER, riskStyle } from '@/theme/risk'

import { basemapStyleUrl, DEFAULT_BASEMAP, type BasemapId } from './basemaps'
import {
  checkpointPoints,
  corridorPoints,
  corridorSegments,
  riskSegments,
  routeLines,
  routesBounds,
  type LevelByIndex,
} from './geojson'
import { MapControls } from './MapControls'
import '@/styles/map.css'

const SOURCES = {
  routes: 'routes',
  risk: 'risk-segments',
  checkpoints: 'checkpoints',
  endpoints: 'endpoints',
  corridorBand: 'corridor-band',
  corridorHalo: 'corridor-halo',
} as const

const LAYERS = {
  corridorBand: 'corridor-band',
  corridorHalo: 'corridor-halo',
  routeLine: 'route-line',
  riskLine: 'risk-line',
  checkpointDots: 'checkpoint-dots',
  checkpointSelected: 'checkpoint-selected',
  endpointDots: 'endpoint-dots',
} as const

const EMPTY = { type: 'FeatureCollection' as const, features: [] }

/** Pulse timing and radii, in px. Slow and small: noticeable, not busy. */
const PULSE_PERIOD_MS = 2400
const PULSE_DOT_MIN = 3.5
const PULSE_DOT_MAX = 5.5
const PULSE_RING_MIN = 7
const PULSE_RING_MAX = 11

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
  onSelectCheckpoint: (index: number | null) => void
  origin?: Place | null | undefined
  destination?: Place | null | undefined
  /**
   * Risk per checkpoint for the selected forecast hour. Null draws no
   * corridor band -- before an analysis, while frames load, or on error.
   */
  corridorLevels?: LevelByIndex | null | undefined
  /** Caption for the frame being shown, e.g. `+12 h · Fri 6:00 PM MST`. */
  corridorLabel?: string | null | undefined
  /**
   * The selected checkpoint and what to show in its popup. The map anchors
   * a popup at the checkpoint and renders `content` inside it.
   */
  popup?: { checkpoint: Checkpoint; content: ReactNode } | null | undefined
}

/**
 * Write every data source for the current props.
 *
 * Separated from the effect so one `try` covers all writes. Any MapLibre
 * failure in here must surface *on the map* and nowhere else: an uncaught
 * throw inside an effect unmounts the whole application, which turns a
 * finished analysis into a blank page and loses the message in the console.
 */
function pushData(
  map: MapLibreMap,
  routes: AnalysedRoute[],
  selectedRouteId: string | null,
  selectedRoute: AnalysedRoute | null,
  origin: Place | null | undefined,
  destination: Place | null | undefined,
  corridorLevels: LevelByIndex | null | undefined,
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

  // The corridor frame: same forward attribution as the risk line, coloured
  // by the selected hour instead of by each checkpoint's ETA.
  const showCorridor = Boolean(selectedRoute && corridorLevels)
  setSourceData(
    map,
    SOURCES.corridorBand,
    showCorridor ? corridorSegments(selectedRoute!, corridorLevels!) : EMPTY,
  )
  setSourceData(
    map,
    SOURCES.corridorHalo,
    showCorridor ? corridorPoints(selectedRoute!, corridorLevels!) : EMPTY,
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
  for (const id of Object.values(SOURCES)) {
    if (!map.getSource(id)) {
      map.addSource(id, { type: 'geojson', data: EMPTY })
    }
  }

  // The corridor band: wide, translucent, under everything else we draw.
  // It is the selected forecast hour, not the ETA view -- the dotted risk
  // line above it stays the ETA view, so both are visible at once and the
  // legend says which is which. Butt caps keep segment boundaries crisp.
  if (!map.getLayer(LAYERS.corridorBand)) {
    map.addLayer({
      id: LAYERS.corridorBand,
      type: 'line',
      source: SOURCES.corridorBand,
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
      paint: {
        'line-color': riskColorExpression(),
        'line-width': 14,
        'line-opacity': 0.32,
      },
    })
  }

  // Thin dashed lines: the basemap's roads stay readable underneath, and
  // the dash reads as "a plan", not a road. Butt caps, because round caps
  // would bleed into the gaps and turn dashes back into a solid line.
  if (!map.getLayer(LAYERS.routeLine)) {
    map.addLayer({
      id: LAYERS.routeLine,
      type: 'line',
      source: SOURCES.routes,
      layout: { 'line-cap': 'butt', 'line-join': 'round' },
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
        'line-width': ['case', ['get', 'isSelected'], 2.5, 1.75],
        'line-opacity': ['case', ['get', 'isSelected'], 0.5, 0.8],
        'line-dasharray': [2, 2],
      },
    })
  }

  // Risk colouring sits above the plain line and only covers the selected
  // route -- three routes of risk colour at once is unreadable. Dotted:
  // a zero-length dash with round caps is a row of dots.
  if (!map.getLayer(LAYERS.riskLine)) {
    map.addLayer({
      id: LAYERS.riskLine,
      type: 'line',
      source: SOURCES.risk,
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': riskColorExpression(),
        'line-width': 3.5,
        'line-opacity': 0.95,
        'line-dasharray': [0, 2],
      },
    })
  }

  // Halo per checkpoint for the selected hour, under the ETA dot so the
  // two levels read as ring (forecast hour) and core (at ETA).
  if (!map.getLayer(LAYERS.corridorHalo)) {
    map.addLayer({
      id: LAYERS.corridorHalo,
      type: 'circle',
      source: SOURCES.corridorHalo,
      paint: {
        'circle-radius': 9,
        'circle-color': riskColorExpression(),
        'circle-opacity': 0.35,
        'circle-stroke-width': 1.5,
        'circle-stroke-color': riskColorExpression(),
        'circle-stroke-opacity': 0.9,
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
      // Blue, not white: the ring has to read on the light Streets basemap
      // as well as on Dark. A faint fill keeps it visible over a dense dot.
      paint: {
        'circle-radius': 8,
        'circle-color': 'rgba(37, 99, 235, 0.18)',
        'circle-stroke-width': 2.5,
        'circle-stroke-color': '#2563EB',
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
  corridorLevels = null,
  corridorLabel = null,
  popup = null,
}: RouteMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  // Counts style loads. Zero means "no style yet"; it increments on the
  // first load and again after every basemap switch, so effects that draw
  // on the style re-run exactly when the style is replaced.
  const [styleGeneration, setStyleGeneration] = useState(0)
  const [styleError, setStyleError] = useState<string | null>(null)
  const [basemap, setBasemap] = useState<BasemapId>(DEFAULT_BASEMAP)
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

  // One MapLibre popup, created on demand and moved rather than recreated.
  // Its body is a plain DOM node that React renders into through a portal,
  // so the popup content is ordinary React -- same chips, same formatting
  // -- and still lives inside the map where the user clicked.
  const popupRef = useRef<Popup | null>(null)
  const [popupNode] = useState(() => document.createElement('div'))
  // True while *we* are removing the popup, so its `close` event does not
  // bounce back as a user dismissal.
  const closingProgrammatically = useRef(false)

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
      closingProgrammatically.current = true
      popupRef.current?.remove()
      popupRef.current = null
      closingProgrammatically.current = false
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

    const clickable = [LAYERS.routeLine, LAYERS.checkpointDots, LAYERS.corridorHalo]
    map.on('click', LAYERS.routeLine, clickRoute)
    map.on('click', LAYERS.checkpointDots, clickCheckpoint)
    map.on('click', LAYERS.corridorHalo, clickCheckpoint)
    for (const layer of clickable) {
      map.on('mouseenter', layer, enter)
      map.on('mouseleave', layer, leave)
    }

    return () => {
      map.off('click', LAYERS.routeLine, clickRoute)
      map.off('click', LAYERS.checkpointDots, clickCheckpoint)
      map.off('click', LAYERS.corridorHalo, clickCheckpoint)
      for (const layer of clickable) {
        map.off('mouseenter', layer, enter)
        map.off('mouseleave', layer, leave)
      }
    }
  }, [ready, styleGeneration])

  // --- data updates -------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    try {
      pushData(
        map,
        routes,
        selectedRouteId,
        selectedRoute,
        origin,
        destination,
        corridorLevels,
      )
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
    corridorLevels,
  ])

  // --- pulse ---------------------------------------------------------------
  // Checkpoints breathe: radius eases up and down on a slow sine so they
  // read as live markers rather than static dots. One rAF loop writes two
  // paint properties; MapLibre only repaints when a value changes, and the
  // loop pauses with the tab because rAF does. Honours reduced-motion.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    if (typeof requestAnimationFrame !== 'function') return
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return

    let frame = 0
    const started = performance.now()
    const tick = (now: number) => {
      const phase = ((now - started) / PULSE_PERIOD_MS) * Math.PI * 2
      const wave = (Math.sin(phase) + 1) / 2 // 0..1, smooth
      try {
        if (map.getLayer(LAYERS.checkpointDots)) {
          map.setPaintProperty(
            LAYERS.checkpointDots,
            'circle-radius',
            PULSE_DOT_MIN + wave * (PULSE_DOT_MAX - PULSE_DOT_MIN),
          )
        }
        if (map.getLayer(LAYERS.checkpointSelected)) {
          map.setPaintProperty(
            LAYERS.checkpointSelected,
            'circle-radius',
            PULSE_RING_MIN + wave * (PULSE_RING_MAX - PULSE_RING_MIN),
          )
        }
      } catch {
        // Style mid-swap; the next style.load restarts this effect.
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [ready, styleGeneration])

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

  // --- popup ---------------------------------------------------------------
  const popupLat = popup?.checkpoint.latitude ?? null
  const popupLng = popup?.checkpoint.longitude ?? null

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return

    if (popupLat === null || popupLng === null) {
      if (popupRef.current) {
        closingProgrammatically.current = true
        popupRef.current.remove()
        closingProgrammatically.current = false
      }
      return
    }

    if (!popupRef.current) {
      const instance = new Popup({
        closeButton: true,
        closeOnClick: false,
        maxWidth: '20rem',
        offset: 14,
        className: 'checkpoint-popup',
      })
      instance.setDOMContent(popupNode)
      instance.on('close', () => {
        if (!closingProgrammatically.current) {
          handlers.current.onSelectCheckpoint(null)
        }
      })
      popupRef.current = instance
    }

    popupRef.current.setLngLat([popupLng, popupLat]).addTo(map)

    // Keyboard users: focus lands in the popup (its close button is the
    // first control) and Escape dismisses it, like a dialog.
    const shell = popupNode.closest('.maplibregl-popup')
    const closeButton = shell?.querySelector<HTMLElement>('.maplibregl-popup-close-button')
    if (closeButton) {
      closeButton.setAttribute('aria-label', 'Close checkpoint weather')
      closeButton.focus({ preventScroll: true })
    }
    const onKeyDown = (event: Event) => {
      if ((event as KeyboardEvent).key === 'Escape') {
        event.stopPropagation()
        handlers.current.onSelectCheckpoint(null)
      }
    }
    const target = shell ?? popupNode
    target.addEventListener('keydown', onKeyDown)
    return () => target.removeEventListener('keydown', onKeyDown)
  }, [ready, styleGeneration, popupLat, popupLng, popupNode])

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

      {corridorLabel && corridorLevels && (
        <div
          className="pointer-events-none absolute left-3 top-3 z-10 rounded-lg border border-hairline bg-panel/90 px-3 py-1.5 text-xs backdrop-blur-sm"
          data-testid="corridor-badge"
        >
          <span className="font-semibold text-ink">Forecast band</span>
          <span className="text-muted"> · {corridorLabel}</span>
        </div>
      )}

      {styleError && (
        <div className="absolute inset-x-3 top-3 z-10">
          <Alert severity="warning" variant="filled">
            <AlertTitle>Map unavailable</AlertTitle>
            {styleError}
          </Alert>
        </div>
      )}

      <MapControls basemap={basemap} onBasemapChange={setBasemap} />

      <MapLegend
        hasSelection={Boolean(selectedRoute)}
        hasCorridor={Boolean(selectedRoute && corridorLevels)}
      />

      {popup && createPortal(popup.content, popupNode)}
    </div>
  )
}

function MapLegend({
  hasSelection,
  hasCorridor,
}: {
  hasSelection: boolean
  hasCorridor: boolean
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
      {hasCorridor && (
        // Two overlays, two meanings. The band is one instant across the
        // whole route; the dots are each checkpoint at its own ETA.
        <p className="m-0 mt-2 max-w-[13rem] text-[0.6875rem] leading-snug text-muted">
          <strong>Wide band & halos:</strong> forecast at the selected hour.{' '}
          <strong>Dots & dotted line:</strong> at each checkpoint's ETA. Click a
          checkpoint for its weather.
        </p>
      )}
    </div>
  )
}

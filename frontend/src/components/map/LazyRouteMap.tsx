import Skeleton from '@mui/material/Skeleton'
import { Suspense, lazy } from 'react'

import type { RouteMapProps } from './RouteMap'

/**
 * MapLibre, loaded on demand.
 *
 * The library is ~1.2 MB — roughly three quarters of the whole bundle. Making
 * the first paint wait for it would block the trip form, which is the only
 * thing a user can act on before an analysis exists. Splitting it out lets
 * the form render immediately while the map streams in behind a skeleton.
 */
const RouteMap = lazy(async () => {
  const module = await import('./RouteMap')
  return { default: module.RouteMap }
})

export function LazyRouteMap(props: RouteMapProps) {
  return (
    <Suspense
      fallback={
        <Skeleton
          variant="rectangular"
          className="h-full w-full rounded-xl"
          sx={{ bgcolor: 'rgba(26, 42, 64, 0.6)' }}
        />
      }
    >
      <RouteMap {...props} />
    </Suspense>
  )
}

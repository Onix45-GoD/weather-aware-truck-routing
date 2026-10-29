import { setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'

/**
 * Point MapLibre at a worker file the build actually ships.
 *
 * MapLibre 6 resolves its tile-parsing worker as
 * `new URL('./maplibre-gl-worker.mjs', import.meta.url)`. In development
 * that is a real file under node_modules; in a production bundle nothing
 * emits it, the request falls through to the SPA fallback and comes back
 * as HTML, and the map renders no tiles with only "Worker failed to load"
 * in the console. Importing the file through Vite's `?url` makes it a
 * hashed, emitted asset and registers that URL before any map is created.
 */
setWorkerUrl(workerUrl)

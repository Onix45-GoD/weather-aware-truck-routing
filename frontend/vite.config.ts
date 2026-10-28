import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  // Tailwind v4 is a Vite plugin — there is no PostCSS config and no
  // `tailwind.config.js`. Theme tokens live in `@theme` inside index.css.
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // Bind IPv4 explicitly. On Windows, Node can resolve `localhost` to
    // IPv6-only, leaving 127.0.0.1 refused -- confusing for anyone who
    // follows the README's URL.
    host: '127.0.0.1',
  },
  optimizeDeps: {
    // MapLibre parses tiles in a Web Worker and locates it by URL. Vite's
    // dependency pre-bundler rewrites the package in a way that breaks that
    // URL in dev, so the worker fails to load and the map renders nothing
    // -- with only a console error to show for it. Excluding it from
    // pre-bundling is the documented fix; production builds are unaffected.
    exclude: ['maplibre-gl'],
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.tsx'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/main.tsx',
        'src/vite-env.d.ts',
      ],
    },
  },
})

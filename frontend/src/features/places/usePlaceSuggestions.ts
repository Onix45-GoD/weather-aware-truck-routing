import { useEffect, useRef, useState } from 'react'

import { fetchPlaceSuggestions } from '@/api/client'
import type { PlaceSuggestion } from '@/api/types'

export interface PlaceSuggestionsState {
  options: PlaceSuggestion[]
  loading: boolean
}

const DEBOUNCE_MS = 250
const MIN_LENGTH = 2
const CACHE_LIMIT = 50

/**
 * Type-ahead candidates for a place field.
 *
 * Debounced, aborted on every keystroke, cached by query, and guarded
 * against a slow earlier response landing after a newer one. The server
 * answers an empty list for anything under two characters, so that case is
 * short-circuited here without a request. `enabled` lets a field hold off
 * until the user has actually typed: the form's default values are not a
 * search.
 */
export function usePlaceSuggestions(
  query: string,
  enabled = true,
): PlaceSuggestionsState {
  const [options, setOptions] = useState<PlaceSuggestion[]>([])
  const [loading, setLoading] = useState(false)
  const cache = useRef(new Map<string, PlaceSuggestion[]>())

  const trimmed = query.trim()

  useEffect(() => {
    if (!enabled || trimmed.length < MIN_LENGTH) {
      // oxlint-disable-next-line react/set-state-in-effect
      setOptions([])
      setLoading(false)
      return
    }

    const cached = cache.current.get(trimmed.toLowerCase())
    if (cached) {
      // oxlint-disable-next-line react/set-state-in-effect
      setOptions(cached)
      setLoading(false)
      return
    }

    const controller = new AbortController()
    let stale = false
    const timer = setTimeout(() => {
      setLoading(true)
      fetchPlaceSuggestions(trimmed, { signal: controller.signal })
        .then((response) => {
          if (stale) return
          if (cache.current.size >= CACHE_LIMIT) {
            const oldest = cache.current.keys().next().value
            if (oldest !== undefined) cache.current.delete(oldest)
          }
          cache.current.set(trimmed.toLowerCase(), response.suggestions)
          setOptions(response.suggestions)
          setLoading(false)
        })
        .catch(() => {
          // Suggestions are a convenience: a failure just means no list.
          // The field still submits whatever was typed.
          if (stale) return
          setOptions([])
          setLoading(false)
        })
    }, DEBOUNCE_MS)

    return () => {
      stale = true
      clearTimeout(timer)
      controller.abort()
    }
  }, [trimmed, enabled])

  return { options, loading }
}

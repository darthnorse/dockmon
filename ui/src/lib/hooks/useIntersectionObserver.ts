/**
 * useIntersectionObserver Hook
 *
 * Detects when an element enters or leaves the viewport.
 * Used to pause sparkline updates for off-screen host cards.
 */

import { useEffect, useRef, useState } from 'react'

interface UseIntersectionObserverOptions {
  threshold?: number
  root?: Element | null
  rootMargin?: string
  enabled?: boolean
}

interface UseIntersectionObserverReturn<T> {
  ref: React.RefObject<T>
  isVisible: boolean
  entry: IntersectionObserverEntry | undefined
}

export function useIntersectionObserver<T extends Element = HTMLDivElement>(
  options: UseIntersectionObserverOptions = {}
): UseIntersectionObserverReturn<T> {
  const { threshold = 0, root = null, rootMargin = '0px', enabled = true } = options
  const ref = useRef<T>(null)
  const [isVisible, setIsVisible] = useState(true)
  const [entry, setEntry] = useState<IntersectionObserverEntry>()

  useEffect(() => {
    const element = ref.current

    // If disabled or no element, assume visible
    if (!enabled || !element) {
      setIsVisible(true)
      return
    }

    // If browser doesn't support IntersectionObserver, assume visible
    if (typeof IntersectionObserver === 'undefined') {
      setIsVisible(true)
      return
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry) {
          setEntry(entry)
          setIsVisible(entry.isIntersecting)
        }
      },
      { threshold, root, rootMargin }
    )

    observer.observe(element)
    return () => observer.disconnect()
  }, [enabled, threshold, root, rootMargin])

  return { ref, isVisible, entry }
}

import { useCallback, useEffect, useRef } from 'react'
import { useSettings } from './useSettings'
import type { RoutePlan } from '@/types'

/**
 * Voice guidance for a planned route (Phase 5.4).
 *
 * Speaks the first two instructions when a route arrives, then offers a
 * "read all steps" action from the route panel. Uses the Web Speech API - no
 * external service, works offline in Chromium and Safari.
 */
export function useVoiceGuidance(route: RoutePlan | null) {
  const { settings } = useSettings()
  const spokenFor = useRef<string | null>(null)

  const speak = useCallback(
    (text: string) => {
      if (!settings.voiceGuidance || typeof window === 'undefined' || !('speechSynthesis' in window)) return
      window.speechSynthesis.cancel()
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.rate = settings.reduceMotion ? 0.92 : 1.0
      utterance.pitch = 1
      utterance.lang = 'en-GB'
      window.speechSynthesis.speak(utterance)
    },
    [settings.voiceGuidance, settings.reduceMotion],
  )

  const stop = useCallback(() => {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel()
  }, [])

  const readAllSteps = useCallback(() => {
    if (!route?.steps?.length) return
    const script = route.steps.map((step) => step.instruction).join(' ')
    speak(script)
  }, [route, speak])

  // Announce a newly planned route automatically (first two steps only).
  useEffect(() => {
    if (!route?.found) return
    const key = `${route.distance_m}-${route.steps[0]?.instruction ?? ''}`
    if (spokenFor.current === key) return
    spokenFor.current = key
    const head = route.steps.slice(0, 2).map((step) => step.instruction).join(' ')
    const grade =
      route.summary?.accessibility_grade === 'step_free'
        ? 'Step-free route found.'
        : route.degraded
          ? 'Warning: no step-free route is available right now.'
          : 'Route found.'
    speak(`${grade} ${route.distance_text ?? `${Math.round(route.distance_m)} metres`}. ${head}`)
  }, [route, speak])

  useEffect(() => stop, [stop])

  const supported = typeof window !== 'undefined' && 'speechSynthesis' in window
  return { speak, stop, readAllSteps, supported }
}

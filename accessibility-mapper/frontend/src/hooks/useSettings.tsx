import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

/**
 * Accessibility settings - the Phase 5.4 control surface.
 * Persisted so a returning wheelchair user does not re-toggle step-free mode.
 */
export interface A11ySettings {
  wheelchairMode: boolean
  highContrast: boolean
  fontScale: number
  voiceGuidance: boolean
  reduceMotion: boolean
  showHeatmap: boolean
  showNetwork: boolean
  showUnverified: boolean
}

const DEFAULTS: A11ySettings = {
  wheelchairMode: true,
  highContrast: false,
  fontScale: 1,
  voiceGuidance: false,
  reduceMotion: false,
  showHeatmap: false,
  showNetwork: true,
  showUnverified: true,
}

const STORAGE_KEY = 'abm.settings'

function load(): A11ySettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULTS
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<A11ySettings>) }
  } catch {
    return DEFAULTS
  }
}

interface SettingsContextValue {
  settings: A11ySettings
  update: (patch: Partial<A11ySettings>) => void
  toggle: (key: keyof A11ySettings) => void
  reset: () => void
}

const SettingsContext = createContext<SettingsContextValue | null>(null)

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<A11ySettings>(load)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
    const root = document.documentElement
    root.classList.toggle('hc', settings.highContrast)
    root.style.fontSize = `${Math.round(16 * settings.fontScale)}px`
    root.dataset.reduceMotion = settings.reduceMotion ? 'true' : 'false'
  }, [settings])

  const update = useCallback((patch: Partial<A11ySettings>) => {
    setSettings((current) => ({ ...current, ...patch }))
  }, [])

  const toggle = useCallback((key: keyof A11ySettings) => {
    setSettings((current) => ({ ...current, [key]: !current[key] }))
  }, [])

  const reset = useCallback(() => setSettings(DEFAULTS), [])

  const value = useMemo(() => ({ settings, update, toggle, reset }), [settings, update, toggle, reset])
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>
}

export function useSettings(): SettingsContextValue {
  const context = useContext(SettingsContext)
  if (!context) throw new Error('useSettings must be used inside <SettingsProvider>')
  return context
}

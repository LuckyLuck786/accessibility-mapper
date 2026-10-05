import { Contrast, EyeOff, Map, Type, Volume2, Zap } from 'lucide-react'
import { Accessibility } from 'lucide-react'
import { useSettings } from '@/hooks/useSettings'
import { Card, Toggle } from './ui'

/**
 * Phase 5.4 - the accessibility control surface. Every control here is itself
 * keyboard-operable and labelled, which is the point of the product.
 */
export function AccessibilityPanel() {
  const { settings, update } = useSettings()

  return (
    <Card title="Accessibility & display">
      <div className="divide-y divide-slate-100">
        <Toggle
          checked={settings.wheelchairMode}
          onChange={(value) => update({ wheelchairMode: value })}
          label={
            <span className="flex items-center gap-2">
              <Accessibility className="h-4 w-4 text-campus-600" aria-hidden /> Step-free / wheelchair mode
            </span>
          }
          hint="Routes never include stairs; blocked ramps, broken lifts and narrow paths are excluded."
        />
        <Toggle
          checked={settings.voiceGuidance}
          onChange={(value) => update({ voiceGuidance: value })}
          label={
            <span className="flex items-center gap-2">
              <Volume2 className="h-4 w-4 text-campus-600" aria-hidden /> Voice guidance
            </span>
          }
          hint="Speaks route summaries and turn-by-turn steps (Web Speech API)."
        />
        <Toggle
          checked={settings.highContrast}
          onChange={(value) => update({ highContrast: value })}
          label={
            <span className="flex items-center gap-2">
              <Contrast className="h-4 w-4 text-campus-600" aria-hidden /> High-contrast palette
            </span>
          }
          hint="Stronger borders, brighter text, reduced transparency."
        />
        <Toggle
          checked={settings.reduceMotion}
          onChange={(value) => update({ reduceMotion: value })}
          label={
            <span className="flex items-center gap-2">
              <Zap className="h-4 w-4 text-campus-600" aria-hidden /> Reduce motion & pulsing markers
            </span>
          }
        />
        <Toggle
          checked={settings.showNetwork}
          onChange={(value) => update({ showNetwork: value })}
          label={
            <span className="flex items-center gap-2">
              <Map className="h-4 w-4 text-campus-600" aria-hidden /> Show path network
            </span>
          }
        />
        <Toggle
          checked={settings.showUnverified}
          onChange={(value) => update({ showUnverified: value })}
          label={
            <span className="flex items-center gap-2">
              <EyeOff className="h-4 w-4 text-campus-600" aria-hidden /> Show unverified reports
            </span>
          }
          hint="Hide community reports that have not been corroborated yet."
        />
        <div className="pt-2">
          <label className="flex items-center justify-between gap-3 text-sm font-medium text-slate-800">
            <span className="flex items-center gap-2">
              <Type className="h-4 w-4 text-campus-600" aria-hidden /> Text size
            </span>
            <span className="flex items-center gap-2">
              <input
                type="range"
                min={0.85}
                max={1.4}
                step={0.05}
                value={settings.fontScale}
                onChange={(event) => update({ fontScale: Number(event.target.value) })}
                aria-label="Text size"
                className="w-32 accent-campus-600"
              />
              <span className="w-10 text-right text-xs text-slate-500">
                {Math.round(settings.fontScale * 100)}%
              </span>
            </span>
          </label>
        </div>
      </div>
    </Card>
  )
}

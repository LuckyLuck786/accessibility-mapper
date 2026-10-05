import { useEffect, useState } from 'react'
import {
  Accessibility,
  AlertTriangle,
  Footprints,
  Navigation,
  Volume2,
  Square,
  Route as RouteIcon,
  Timer,
} from 'lucide-react'
import { apiError, planRoute } from '@/services/api'
import { useGeolocation } from '@/hooks/useGeolocation'
import { useSettings } from '@/hooks/useSettings'
import { useVoiceGuidance } from '@/hooks/useSpeech'
import type { Preset, RoutePlan } from '@/types'
import { Badge, Button, Spinner, Toggle } from './ui'

type Waypoint = { latitude: number; longitude: number; label: string } | null

interface RoutePanelProps {
  presets: Preset[]
  wheelchairMode: boolean
  onWheelchairModeChange: (value: boolean) => void
  onRoute: (route: RoutePlan | null) => void
  focusRoute: () => void
  onPickOnMap: (target: 'origin' | 'destination') => void
  pickTarget: 'origin' | 'destination' | null
}

const CAMPUS_FALLBACK: [number, number] = [47.6555, -122.306]

export function RoutePanel({
  presets,
  wheelchairMode,
  onWheelchairModeChange,
  onRoute,
  focusRoute,
  onPickOnMap,
  pickTarget,
}: RoutePanelProps) {
  const [origin, setOrigin] = useState<Waypoint>(null)
  const [destination, setDestination] = useState<Waypoint>(null)
  const [route, setRoute] = useState<RoutePlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { fix, locate, isLocating } = useGeolocation()
  const { settings } = useSettings()
  const { readAllSteps, stop, supported } = useVoiceGuidance(route)

  useEffect(() => {
    if (fix) {
      const here = { latitude: fix.latitude, longitude: fix.longitude, label: 'My location' }
      setOrigin((current) => current ?? here)
    }
  }, [fix])

  useEffect(() => {
    onRoute(route)
  }, [onRoute, route])

  async function handlePlan() {
    if (!origin || !destination) {
      setError('Choose both an origin and a destination.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await planRoute({
        start_lat: origin.latitude,
        start_lng: origin.longitude,
        end_lat: destination.latitude,
        end_lng: destination.longitude,
        wheelchair_accessible: wheelchairMode,
        start_label: origin.label,
        end_label: destination.label,
      })
      setRoute(result)
      onRoute(result)
      focusRoute()
    } catch (planError) {
      setError(apiError(planError))
      setRoute(null)
      onRoute(null)
    } finally {
      setLoading(false)
    }
  }

  function selectPreset(which: 'origin' | 'destination', preset: Preset) {
    const waypoint: Waypoint = {
      latitude: preset.latitude,
      longitude: preset.longitude,
      label: preset.label,
    }
    if (which === 'origin') setOrigin(waypoint)
    else setDestination(waypoint)
  }

  return (
    <div className="space-y-4">
      <div className="rounded-2xl bg-white p-4 shadow-panel ring-1 ring-slate-200/70">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <RouteIcon className="h-4 w-4 text-campus-600" aria-hidden />
            Accessible route planner
          </h2>
          <Toggle
            checked={wheelchairMode}
            onChange={onWheelchairModeChange}
            label={
              <span className="flex items-center gap-1.5 text-xs font-semibold">
                <Accessibility className="h-4 w-4" aria-hidden />
                Step-free
              </span>
            }
          />
        </div>

        <div className="space-y-2">
          <WaypointPicker
            idPrefix="origin"
            label="Origin"
            waypoint={origin}
            onClear={() => setOrigin(null)}
            onUseMyLocation={() => {
              locate()
            }}
            locating={isLocating}
            onPickOnMap={() => onPickOnMap('origin')}
            picking={pickTarget === 'origin'}
          />
          <WaypointPicker
            idPrefix="destination"
            label="Destination"
            waypoint={destination}
            onClear={() => setDestination(null)}
            onPickOnMap={() => onPickOnMap('destination')}
            picking={pickTarget === 'destination'}
          />
        </div>

        <div className="mt-3">
          <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Quick destinations
          </p>
          <div className="flex flex-wrap gap-1.5">
            {presets.map((preset) => (
              <button
                key={preset.node_id}
                type="button"
                onClick={() => selectPreset('destination', preset)}
                className={`rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-campus-600 ${
                  destination?.label === preset.label
                    ? 'bg-campus-600 text-white ring-campus-700'
                    : 'bg-slate-50 text-slate-700 ring-slate-200 hover:bg-slate-100'
                }`}
                title={preset.note ?? preset.label}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>

        <Button onClick={handlePlan} disabled={loading} className="mt-4 w-full">
          <Navigation className="h-4 w-4" aria-hidden />
          {loading ? 'Planning…' : 'Plan accessible route'}
        </Button>
        {error && (
          <p role="alert" className="mt-2 text-sm font-medium text-red-600">
            {error}
          </p>
        )}
      </div>

      {loading && (
        <div className="rounded-2xl bg-white p-4 text-center shadow-panel ring-1 ring-slate-200/70">
          <Spinner label="Routing over the campus graph" />
        </div>
      )}

      {route && route.found && (
        <RouteResultCard
          route={route}
          onReplay={readAllSteps}
          onStop={stop}
          voiceSupported={supported && settings.voiceGuidance}
        />
      )}

      {route && !route.found && (
        <div className="rounded-2xl bg-red-50 p-4 ring-1 ring-red-200">
          <h3 className="flex items-center gap-2 text-sm font-semibold text-red-800">
            <AlertTriangle className="h-4 w-4" aria-hidden /> No route available
          </h3>
          <p className="mt-1 text-sm text-red-700">{route.message}</p>
        </div>
      )}
    </div>
  )
}

function WaypointPicker({
  idPrefix,
  label,
  waypoint,
  onClear,
  onUseMyLocation,
  locating,
  onPickOnMap,
  picking,
}: {
  idPrefix: string
  label: string
  waypoint: Waypoint
  onClear: () => void
  onUseMyLocation?: () => void
  locating?: boolean
  onPickOnMap: () => void
  picking: boolean
}) {
  return (
    <div
      className={`rounded-xl px-3 py-2 ring-1 transition ${
        picking ? 'bg-red-50 ring-red-300' : 'bg-slate-50 ring-slate-200'
      }`}
    >
      <div className="flex items-center justify-between">
        <label htmlFor={`${idPrefix}-display`} className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          {label}
        </label>
        <span className="flex gap-1">
          {onUseMyLocation && (
            <button
              type="button"
              onClick={onUseMyLocation}
              className="rounded-lg px-1.5 py-0.5 text-[11px] font-semibold text-campus-700 hover:bg-campus-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
            >
              {locating ? 'locating…' : '📍 Use my location'}
            </button>
          )}
          <button
            type="button"
            onClick={onPickOnMap}
            className={`rounded-lg px-1.5 py-0.5 text-[11px] font-semibold focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600 ${
              picking ? 'bg-red-600 text-white' : 'text-campus-700 hover:bg-campus-50'
            }`}
          >
            {picking ? 'tap the map…' : 'Pin on map'}
          </button>
          {waypoint && (
            <button
              type="button"
              onClick={onClear}
              aria-label={`Clear ${label}`}
              className="rounded-lg px-1.5 py-0.5 text-[11px] font-semibold text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
            >
              ✕
            </button>
          )}
        </span>
      </div>
      <p id={`${idPrefix}-display`} className="mt-0.5 truncate text-sm font-medium text-slate-800" aria-live="polite">
        {waypoint ? waypoint.label : 'Not set'}
        {waypoint && (
          <span className="ml-1 text-[11px] font-normal text-slate-400">
            {waypoint.latitude.toFixed(5)}, {waypoint.longitude.toFixed(5)}
          </span>
        )}
      </p>
    </div>
  )
}

function RouteResultCard({
  route,
  onReplay,
  onStop,
  voiceSupported,
}: {
  route: RoutePlan
  onReplay: () => void
  onStop: () => void
  voiceSupported: boolean
}) {
  return (
    <div className="rounded-2xl bg-white p-4 shadow-panel ring-1 ring-slate-200/70">
      <header className="flex items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-900">Route summary</h3>
        <Badge tone={route.degraded ? 'bg-red-100 text-red-900 ring-red-300' : 'bg-emerald-100 text-emerald-900 ring-emerald-300'}>
          {route.degraded ? 'Assisted route' : 'Recommended'}
        </Badge>
      </header>

      <dl className="mt-3 grid grid-cols-1 gap-2 text-center sm:grid-cols-3">
        <div className="rounded-xl bg-slate-50 px-2 py-2 ring-1 ring-slate-200">
          <dt className="text-[11px] font-semibold uppercase text-slate-500">Distance</dt>
          <dd className="text-lg font-bold text-slate-900">{route.distance_text}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 px-2 py-2 ring-1 ring-slate-200">
          <dt className="text-[11px] font-semibold uppercase text-slate-500">Time</dt>
          <dd className="text-lg font-bold text-slate-900">{route.duration_text}</dd>
        </div>
        <div className="rounded-xl bg-slate-50 px-2 py-2 ring-1 ring-slate-200">
          <dt className="text-[11px] font-semibold uppercase text-slate-500">Mode</dt>
          <dd className="flex items-center justify-center text-lg font-bold text-slate-900">
            {route.wheelchair_accessible ? <Accessibility className="h-5 w-5 text-campus-600" aria-label="wheelchair" /> : <Footprints className="h-5 w-5" aria-label="walking" />}
          </dd>
        </div>
      </dl>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone={route.degraded ? 'bg-red-100 text-red-900 ring-red-300' : 'bg-emerald-100 text-emerald-900 ring-emerald-300'}>
          {route.summary?.accessibility_grade.replace(/_/g, ' ') ?? 'route'}
        </Badge>
        {route.summary?.min_width_m && (
          <Badge>min width {route.summary.min_width_m} m</Badge>
        )}
        {route.summary && route.summary.max_incline_pct > 0 && (
          <Badge>max incline {route.summary.max_incline_pct}%</Badge>
        )}
        {route.barriers_on_route.length > 0 && (
          <Badge tone="bg-red-100 text-red-900 ring-red-300">
            {route.barriers_on_route.length} hazard(s) on route
          </Badge>
        )}
      </div>

      {route.warnings.length > 0 && (
        <ul className="mt-3 space-y-1.5" aria-label="Safety alerts">
          {route.warnings.slice(0, 4).map((warning, index) => (
            <li
              key={`${warning.code}-${index}`}
              className={`flex items-start gap-2 rounded-xl px-3 py-2 text-xs font-medium ${
                warning.severity === 'critical'
                  ? 'bg-red-50 text-red-800 ring-1 ring-red-200'
                  : warning.severity === 'high'
                    ? 'bg-orange-50 text-orange-800 ring-1 ring-orange-200'
                    : 'bg-amber-50 text-amber-800 ring-1 ring-amber-200'
              }`}
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              {warning.message}
            </li>
          ))}
        </ul>
      )}

      {voiceSupported && (
        <div className="mt-3 flex gap-2">
          <Button variant="secondary" onClick={onReplay} className="flex-1 text-xs">
            <Volume2 className="h-4 w-4" aria-hidden /> Read route aloud
          </Button>
          <Button variant="ghost" onClick={onStop} title="Stop narration" className="px-2">
            <Square className="h-4 w-4" aria-hidden />
            <span className="sr-only">Stop narration</span>
          </Button>
        </div>
      )}

      <details className="mt-3 rounded-xl bg-slate-50 ring-1 ring-slate-200">
        <summary className="cursor-pointer px-3 py-2 text-xs font-semibold text-slate-700">
          Turn-by-turn directions ({route.steps.length} steps) <Timer className="ml-1 inline h-3 w-3" aria-hidden />
        </summary>
        <ol className="space-y-2 px-3 pb-3">
          {route.steps.map((step) => (
            <li key={step.index} className="border-l-2 border-campus-500 pl-3">
              <p className="text-sm font-medium text-slate-900">
                <span className="mr-1 text-[11px] font-bold text-campus-600">{step.index + 1}.</span>
                {step.instruction}
              </p>
              <p className="text-[11px] text-slate-500">
                {step.distance_m > 0 && <>{step.distance_m} m · </>}
                {step.compass}
                {!step.is_step_free && <span className="ml-1 font-semibold text-red-600">· steps</span>}
              </p>
              {step.cautions.map((caution) => (
                <p key={caution.barrier_id} className="mt-0.5 text-[11px] font-semibold text-red-600">
                  ⚠ {caution.message}
                </p>
              ))}
            </li>
          ))}
        </ol>
      </details>
    </div>
  )
}

export { CAMPUS_FALLBACK }

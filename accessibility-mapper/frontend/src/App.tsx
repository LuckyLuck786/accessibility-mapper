import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Flame,
  Loader2,
  MapPin,
  Plus,
  Settings2,
  Wrench,
  WifiOff,
} from 'lucide-react'
import { AdminDashboard } from '@/components/AdminDashboard'
import { AccessibilityPanel } from '@/components/AccessibilityPanel'
import { BarrierDetailCard } from '@/components/BarrierDetailCard'
import { BarrierReportModal } from '@/components/BarrierReportModal'
import { MapView } from '@/components/MapView'
import { RoutePanel } from '@/components/RoutePanel'
import { Badge, Button, relativeTime } from '@/components/ui'
import { useCampusData } from '@/hooks/useCampusData'
import { SettingsProvider, useSettings } from '@/hooks/useSettings'
import type { Barrier, RoutePlan } from '@/types'

const CAMPUS_CENTER: [number, number] = [47.6555, -122.306]
const CAMPUS_ZOOM = 16

export default function App() {
  return (
    <SettingsProvider>
      <Shell />
    </SettingsProvider>
  )
}

type PickTarget = 'origin' | 'destination' | 'report' | null

function Shell() {
  const { settings, toggle } = useSettings()
  const { overview, barriers, network, presets, categories, error, loading, lastUpdated, refresh } =
    useCampusData()

  const [route, setRoute] = useState<RoutePlan | null>(null)
  const [selectedBarrier, setSelectedBarrier] = useState<Barrier | null>(null)
  const [reportOpen, setReportOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [pickTarget, setPickTarget] = useState<PickTarget>(null)
  const [pickedPoint, setPickedPoint] = useState<{ latitude: number; longitude: number } | null>(null)
  const [focus, setFocus] = useState<{ latitude: number; longitude: number; zoom?: number } | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 4200)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'r' && !event.metaKey && !event.ctrlKey && !(event.target instanceof HTMLInputElement) && !(event.target instanceof HTMLTextAreaElement)) {
        setPickTarget('report')
        setReportOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const handleMapClick = useCallback(
    (latitude: number, longitude: number) => {
      setPickedPoint({ latitude, longitude })
      if (pickTarget === 'report') {
        // keep the pin and let the modal open with it pre-filled
      }
      setPickTarget(null)
    },
    [pickTarget],
  )

  const handleReported = useCallback(
    (payload: { message: string }) => {
      setToast(payload.message)
      refresh()
    },
    [refresh],
  )

  const heatPoints = useMemo(() => {
    if (!barriers) return []
    // Aggregate client-side from live barriers; the analytics endpoint feeds the
    // dashboard view with the server-side weighted version.
    const cells = new Map<string, { lat: number; lng: number; intensity: number; count: number }>()
    for (const feature of barriers.features) {
      const props = feature.properties
      const key = `${props.latitude.toFixed(3)}:${props.longitude.toFixed(3)}`
      const entry = cells.get(key) ?? { lat: props.latitude, lng: props.longitude, intensity: 0, count: 0 }
      entry.intensity += props.severity * (1 + 0.15 * props.confirmations)
      entry.count += 1
      cells.set(key, entry)
    }
    return Array.from(cells.values()).map((cell) => ({
      latitude: cell.lat,
      longitude: cell.lng,
      intensity: cell.intensity,
      count: cell.count,
      active_count: cell.count,
      resolved_count: 0,
      dominant_category: 'obstacle' as const,
      dominant_label: '',
      categories: {},
      location_name: null,
      recurring: cell.count >= 3,
    }))
  }, [barriers])

  return (
    <div className="flex h-full flex-col bg-slate-100">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[1200] focus:rounded-lg focus:bg-campus-700 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to map
      </a>

      <header className="z-[600] flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 shadow-sm">
        <img src="/favicon.svg" alt="" className="hidden h-8 w-8 sm:block" onError={(event) => { event.currentTarget.style.display = 'none' }} />
        <div className="min-w-0">
          <h1 className="truncate text-sm font-bold text-slate-900">
            {overview?.app ?? 'Campus Accessibility Mapper'}
          </h1>
          <p className="text-[11px] text-slate-500">
            {overview
              ? `${overview.graph.nodes} nodes · ${overview.graph.edges} paths · CV: ${overview.cv.engine} · ${overview.database}`
              : 'Connecting to the campus API…'}
          </p>
        </div>

        <span className="ml-auto flex items-center gap-1.5">
          {error && (
            <Badge tone="bg-red-100 text-red-800 ring-red-300">
              <WifiOff className="h-3 w-3" aria-hidden /> {error}
            </Badge>
          )}
          {lastUpdated && !error && (
            <span className="hidden text-[11px] text-slate-400 md:block">
              live · updated {relativeTime(lastUpdated.toISOString())}
            </span>
          )}
          <button
            type="button"
            onClick={() => toggle('showHeatmap')}
            aria-pressed={settings.showHeatmap}
            className={`hidden items-center gap-1.5 rounded-xl px-2.5 py-1.5 text-xs font-semibold ring-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600 sm:inline-flex ${
              settings.showHeatmap ? 'bg-orange-500 text-white ring-orange-600' : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50'
            }`}
          >
            <Flame className="h-4 w-4" aria-hidden /> Heatmap
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen((value) => !value)}
            aria-expanded={settingsOpen}
            className="inline-flex items-center gap-1.5 rounded-xl bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
          >
            <Settings2 className="h-4 w-4" aria-hidden /> A11y
          </button>
          <Button variant="secondary" onClick={() => setAdminOpen(true)}>
            <Wrench className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Facilities</span>
          </Button>
          <Button
            onClick={() => {
              setPickTarget('report')
              setReportOpen(true)
            }}
          >
            <Plus className="h-4 w-4" aria-hidden />
            <span className="hidden sm:inline">Report barrier</span>
          </Button>
        </span>
      </header>

      <div id="main-content" className="relative flex min-h-0 flex-1">
        {/* --- map ------------------------------------------------------ */}
        <main className="relative min-w-0 flex-1">
          {loading && (
            <div className="absolute inset-0 z-[400] flex items-center justify-center bg-slate-100/80">
              <span className="inline-flex items-center gap-2 text-sm font-medium text-slate-600">
                <Loader2 className="h-5 w-5 animate-spin text-campus-600" aria-hidden />
                Loading campus…
              </span>
            </div>
          )}
          <MapView
            network={network}
            barriers={barriers}
            route={route}
            heatmap={heatPoints}
            showNetwork={settings.showNetwork}
            showHeatmap={settings.showHeatmap}
            showUnverified={settings.showUnverified}
            pickMode={pickTarget !== null}
            pickPoint={pickTarget === 'report' ? pickedPoint : null}
            focus={focus}
            center={CAMPUS_CENTER}
            zoom={CAMPUS_ZOOM}
            onMapClick={handleMapClick}
            onBarrierSelect={setSelectedBarrier}
          />
        </main>

        {/* --- sidebar ---------------------------------------------------- */}
        <aside
          className={`absolute inset-y-0 right-0 z-[500] w-[380px] max-w-[92vw] space-y-3 overflow-y-auto bg-slate-100 p-3 shadow-panel transition-transform lg:static lg:z-auto lg:translate-x-0 ${
            pickTarget === 'report' ? 'pointer-events-none opacity-60' : ''
          }`}
          aria-label="Controls and information panels"
        >
          {selectedBarrier && (
            <BarrierDetailCard
              barrier={selectedBarrier}
              onClose={() => setSelectedBarrier(null)}
              onUpdated={(updated) => {
                setSelectedBarrier(updated)
                refresh()
                setToast(`Barrier #${updated.id}: ${updated.status.replace('_', ' ')}`)
              }}
            />
          )}

          <RoutePanel
            presets={presets}
            wheelchairMode={settings.wheelchairMode}
            onWheelchairModeChange={(value) => {
              toggle('wheelchairMode')
              void value
            }}
            onRoute={setRoute}
            focusRoute={() => {
              if (route?.coordinates.length) {
                const [lng, lat] = route.coordinates[Math.floor(route.coordinates.length / 2)]
                setFocus({ latitude: lat, longitude: lng, zoom: 17 })
              }
            }}
            onPickOnMap={(target) => {
              setPickTarget(target)
              setReportOpen(false)
            }}
            pickTarget={pickTarget === 'origin' || pickTarget === 'destination' ? pickTarget : null}
          />

          {settingsOpen && <AccessibilityPanel />}

          <footer className="px-1 pb-2 text-[11px] leading-relaxed text-slate-400">
            {overview?.formula}
            <br />
            Auto-verify ≥ {overview?.policies.auto_verify_confidence ?? 0.85} confidence or{' '}
            {overview?.policies.consensus_confirmations ?? 2} confirmations · duplicate merge radius{' '}
            {overview?.policies.duplicate_radius_m ?? 15} m
          </footer>
        </aside>
      </div>

      <BarrierReportModal
        open={reportOpen}
        onClose={() => {
          setReportOpen(false)
          if (pickTarget === 'report') setPickTarget(null)
        }}
        categories={categories}
        pickedPoint={pickTarget === 'report' ? pickedPoint : null}
        onPickOnMap={() => {
          setReportOpen(false)
          setPickTarget('report')
        }}
        onReported={handleReported}
      />

      <AdminDashboard
        open={adminOpen}
        onClose={() => setAdminOpen(false)}
        onChanged={refresh}
        onFocusBarrier={(latitude, longitude) => {
          setAdminOpen(false)
          setFocus({ latitude, longitude, zoom: 18 })
        }}
      />

      {toast && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 left-1/2 z-[1100] -translate-x-1/2 rounded-2xl bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white shadow-2xl"
        >
          <span className="flex items-center gap-2">
            <MapPin className="h-4 w-4 text-emerald-400" aria-hidden />
            {toast}
          </span>
        </div>
      )}
    </div>
  )
}

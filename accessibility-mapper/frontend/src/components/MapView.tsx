import { useEffect, useMemo } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import { HeatmapCanvas } from './HeatmapCanvas'
import type { Barrier, BarrierCollection, HeatPoint, NetworkCollection, RoutePlan } from '@/types'

export const CATEGORY_GLYPHS: Record<string, string> = {
  blocked_ramp: '🛑',
  broken_lift: '🛗',
  narrow_path: '↔️',
  construction: '🚧',
  obstacle: '⚠️',
  missing_signage: '❓',
}

const KIND_STYLE: Record<string, { color: string; dash?: string; weight: number }> = {
  footpath: { color: '#475569', weight: 3 },
  corridor: { color: '#0f766e', weight: 3 },
  ramp: { color: '#059669', weight: 4 },
  stairs: { color: '#dc2626', weight: 4, dash: '2 6' },
  elevator: { color: '#7c3aed', weight: 4, dash: '6 4' },
  crossing: { color: '#2563eb', weight: 3, dash: '10 6' },
}

export interface MapViewProps {
  network: NetworkCollection | null
  barriers: BarrierCollection | null
  route: RoutePlan | null
  heatmap: HeatPoint[]
  showNetwork: boolean
  showHeatmap: boolean
  showUnverified: boolean
  pickMode: boolean
  pickPoint: { latitude: number; longitude: number } | null
  focus: { latitude: number; longitude: number; zoom?: number } | null
  center: [number, number]
  zoom: number
  onMapClick: (latitude: number, longitude: number) => void
  onBarrierSelect: (barrier: Barrier) => void
}

function barrierIcon(barrier: Barrier): L.DivIcon {
  const glyph = CATEGORY_GLYPHS[barrier.category] ?? '⚠️'
  const ring =
    barrier.status === 'in_progress'
      ? 'ring-sky-400'
      : barrier.status === 'verified'
        ? 'ring-white'
        : 'ring-white/70 ring-dashed'
  const pulse = barrier.is_hard_block && barrier.status !== 'resolved' ? 'abm-pulse' : ''
  const size = 30 + Math.min(8, barrier.confirmations * 2)
  return L.divIcon({
    className: 'abm-marker',
    html: `<span class="abm-marker-inner ${ring} ${pulse}" style="--size:${size}px;background:${barrier.color}" role="img" aria-label="${barrier.label}, ${barrier.status}"><span aria-hidden="true">${glyph}</span></span>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    tooltipAnchor: [size / 2, 0],
  })
}

function ClickCatcher({ onMapClick, pickMode }: { onMapClick: (lat: number, lng: number) => void; pickMode: boolean }) {
  useMapEvents({
    click(event) {
      if (pickMode) onMapClick(event.latlng.lat, event.latlng.lng)
    },
  })
  return null
}

function MapFocus({ focus }: { focus: MapViewProps['focus'] }) {
  const map = useMap()
  useEffect(() => {
    if (!focus) return
    map.flyTo([focus.latitude, focus.longitude], focus.zoom ?? 18, { duration: 0.8 })
  }, [focus, map])
  return null
}

function FitOnLoad({ center, zoom, network }: { center: [number, number]; zoom: number; network: NetworkCollection | null }) {
  const map = useMap()
  const fitted = useMemo(() => ({ done: false }), [])
  useEffect(() => {
    if (fitted.done || !network) return
    const lats: number[] = []
    const lngs: number[] = []
    for (const feature of network.features) {
      if (feature.geometry.type === 'Point') {
        lats.push(feature.geometry.coordinates[1])
        lngs.push(feature.geometry.coordinates[0])
      }
    }
    if (lats.length > 1) {
      map.fitBounds(
        L.latLngBounds(
          [Math.min(...lats), Math.min(...lngs)],
          [Math.max(...lats), Math.max(...lngs)],
        ),
        { padding: [24, 24] },
      )
    } else {
      map.setView(center, zoom)
    }
    fitted.done = true
  }, [center, fitted, map, network, zoom])
  return null
}

export function MapView({
  network,
  barriers,
  route,
  heatmap,
  showNetwork,
  showHeatmap,
  showUnverified,
  pickMode,
  pickPoint,
  focus,
  center,
  zoom,
  onMapClick,
  onBarrierSelect,
}: MapViewProps) {
  type EdgeFeature = { type: 'Feature'; geometry: { type: 'LineString'; coordinates: [number, number][] }; properties: import('@/types').EdgeProps }
  type NodeFeature = { type: 'Feature'; geometry: { type: 'Point'; coordinates: [number, number] }; properties: import('@/types').NodeProps }
  const edges = useMemo(
    () =>
      (network?.features ?? []).filter(
        (feature): feature is EdgeFeature => feature.geometry.type === 'LineString',
      ),
    [network],
  )
  const nodes = useMemo(
    () =>
      (network?.features ?? []).filter(
        (feature): feature is NodeFeature => feature.geometry.type === 'Point',
      ),
    [network],
  )
  const visibleBarriers = useMemo(
    () =>
      (barriers?.features ?? []).filter(
        (feature) => showUnverified || feature.properties.status !== 'unverified',
      ),
    [barriers, showUnverified],
  )

  const routeLatLng = useMemo(
    () => (route?.coordinates ?? []).map(([lng, lat]) => [lat, lng] as [number, number]),
    [route],
  )

  return (
    <div className={`relative h-full w-full ${pickMode ? 'cursor-crosshair' : ''}`}>
      <MapContainer
        center={center}
        zoom={zoom}
        scrollWheelZoom
        zoomControl
        className="h-full w-full"
        aria-label="Campus accessibility map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        <FitOnLoad center={center} zoom={zoom} network={network} />
        <MapFocus focus={focus} />
        <ClickCatcher onMapClick={onMapClick} pickMode={pickMode} />

        {showNetwork &&
          edges.map((feature) => {
            const props = feature.properties
            const style = KIND_STYLE[props.kind] ?? KIND_STYLE.footpath
            const positions = feature.geometry.coordinates.map(([lng, lat]) => [lat, lng] as [number, number])
            const severed = props.step_free_blocked || (props.active_barriers_count ?? 0) > 0
            return (
              <Polyline
                key={`edge-${props.id}`}
                positions={positions}
                pathOptions={{
                  color: severed ? '#dc2626' : style.color,
                  weight: severed ? style.weight + 1.5 : style.weight,
                  dashArray: severed ? '4 6' : style.dash,
                  opacity: 0.85,
                }}
              >
                <Tooltip sticky>
                  <span className="text-xs font-semibold">{props.name}</span>
                  <br />
                  <span className="text-[11px]">
                    {props.kind} · {Math.round(props.distance_m)} m · {props.is_step_free ? 'step-free' : 'steps'}
                    {props.width_m ? ` · ${props.width_m} m wide` : ''}
                    {props.incline_pct ? ` · ${props.incline_pct}% incline` : ''}
                  </span>
                  {severed && (
                    <span className="block text-[11px] font-semibold text-red-600">
                      {props.active_barriers_count} active barrier(s)
                    </span>
                  )}
                </Tooltip>
              </Polyline>
            )
          })}

        {showNetwork &&
          nodes.map((feature) => {
            const props = feature.properties
            const [lng, lat] = feature.geometry.coordinates
            if (props.kind === 'intersection') return null
            const isLift = props.has_elevator || props.kind === 'lift'
            const color = props.kind === 'entrance' ? (props.is_step_free ? '#059669' : '#dc2626') : isLift ? '#7c3aed' : '#0c2340'
            return (
              <CircleMarker
                key={`node-${props.id}`}
                center={[lat, lng]}
                radius={props.kind === 'building' ? 6 : 5}
                pathOptions={{
                  color,
                  fillColor: props.is_entrance ? color : '#ffffff',
                  fillOpacity: 0.9,
                  weight: 2,
                }}
              >
                <Tooltip>
                  <span className="text-xs font-semibold">{props.name}</span>
                  <br />
                  <span className="text-[11px]">
                    {props.kind}
                    {props.has_elevator ? ' · lift available' : ''}
                    {props.is_entrance ? (props.is_step_free ? ' · step-free entrance' : ' · steps at entrance') : ''}
                  </span>
                </Tooltip>
              </CircleMarker>
            )
          })}

        {visibleBarriers.map((feature) => {
          const barrier = feature.properties
          const [lng, lat] = feature.geometry.coordinates
          return (
            <Marker
              key={`barrier-${barrier.id}-${barrier.status}`}
              position={[lat, lng]}
              icon={barrierIcon(barrier)}
              eventHandlers={{ click: () => onBarrierSelect(barrier) }}
              keyboard
            >
              <Tooltip direction="top" offset={[0, -14]}>
                <span className="text-xs font-semibold">
                  {CATEGORY_GLYPHS[barrier.category]} {barrier.label}
                </span>
                <br />
                <span className="text-[11px]">
                  {barrier.status} · {Math.round(barrier.confidence * 100)}% confidence ·{' '}
                  {barrier.confirmations} confirmation(s)
                </span>
              </Tooltip>
            </Marker>
          )
        })}

        {route && routeLatLng.length > 1 && (
          <>
            <Polyline
              positions={routeLatLng}
              pathOptions={{
                color: route.degraded ? '#dc2626' : '#0284c7',
                weight: 7,
                opacity: 0.35,
                lineCap: 'round',
              }}
            />
            <Polyline
              positions={routeLatLng}
              pathOptions={{
                color: route.degraded ? '#b91c1c' : '#0369a1',
                weight: 4,
                dashArray: route.degraded ? '6 8' : undefined,
                lineCap: 'round',
              }}
            >
              <Tooltip sticky>
                <span className="text-xs font-semibold">
                  {route.degraded ? 'Assisted route (contains barriers)' : 'Recommended accessible route'}
                </span>
                <br />
                <span className="text-[11px]">
                  {route.distance_text} · {route.duration_text} · {route.algorithm}
                </span>
              </Tooltip>
            </Polyline>
            <CircleMarker
              center={routeLatLng[0]}
              radius={8}
              pathOptions={{ color: '#0369a1', fillColor: '#ffffff', fillOpacity: 1, weight: 3 }}
            >
              <Tooltip>Start: {route.steps[0]?.road_name ?? 'origin'}</Tooltip>
            </CircleMarker>
            <CircleMarker
              center={routeLatLng[routeLatLng.length - 1]}
              radius={9}
              pathOptions={{ color: '#059669', fillColor: '#059669', fillOpacity: 0.95, weight: 3 }}
            >
              <Tooltip>Destination</Tooltip>
            </CircleMarker>
          </>
        )}

        {pickPoint && (
          <CircleMarker
            center={[pickPoint.latitude, pickPoint.longitude]}
            radius={10}
            pathOptions={{ color: '#dc2626', fillColor: '#dc2626', fillOpacity: 0.4, weight: 3, dashArray: '4 4' }}
          >
            <Tooltip>Report location (drag-pin precision coming soon)</Tooltip>
          </CircleMarker>
        )}
      </MapContainer>

      {pickMode && (
        <div className="pointer-events-none absolute left-1/2 top-3 z-[500] -translate-x-1/2 rounded-full bg-red-600 px-4 py-1.5 text-sm font-semibold text-white shadow-lg">
          Tap the map to drop the barrier pin
        </div>
      )}

      {showHeatmap && <HeatmapCanvas points={heatmap} />}
    </div>
  )
}

/** Shared API contracts - mirrors backend/app/schemas. */

export * from './space'

export type BarrierCategory =
  | 'blocked_ramp'
  | 'broken_lift'
  | 'narrow_path'
  | 'construction'
  | 'obstacle'
  | 'missing_signage'

export type BarrierStatus = 'unverified' | 'verified' | 'in_progress' | 'resolved' | 'expired'

export type TicketPriority = 'low' | 'medium' | 'high' | 'critical'
export type TicketStatus = 'open' | 'in_progress' | 'resolved'

export interface Barrier {
  id: number
  category: BarrierCategory
  label: string
  severity: number
  color: string
  latitude: number
  longitude: number
  confidence: number
  status: BarrierStatus
  description: string | null
  redacted_faces: number
  redacted_plates: number
  detection_source: string
  edge_id: string | null
  reporter_label: string
  confirmations: number
  ticket_id: number | null
  is_active: boolean
  is_hard_block: boolean
  created_at: string | null
  updated_at: string | null
  verified_at: string | null
  resolved_at: string | null
  expires_at: string | null
  age_hours: number
  resolution_hours: number | null
  image_url?: string
}

export interface CategoryInfo {
  category: BarrierCategory
  label: string
  color: string
  severity: number
  step_free_blocking: boolean
  active_count: number
}

export interface GeoJsonPoint {
  type: 'Point'
  coordinates: [number, number]
}

export interface GeoJsonLine {
  type: 'LineString'
  coordinates: [number, number][]
}

export interface BarrierFeature {
  type: 'Feature'
  geometry: GeoJsonPoint
  properties: Barrier
}

export interface BarrierCollection {
  type: 'FeatureCollection'
  features: BarrierFeature[]
  meta: {
    count: number
    generated_at: string
    categories: string[]
    verified: number
    unverified: number
    in_progress: number
  }
}

export interface NodeProps {
  id: string
  name: string
  kind: string
  has_elevator: boolean
  is_entrance: boolean
  is_step_free: boolean
  building_code: string | null
  campus_zone: string | null
}

export interface EdgeProps {
  id: string
  name: string
  kind: string
  source_node_id: string
  target_node_id: string
  distance_m: number
  is_step_free: boolean
  width_m: number
  incline_pct: number
  active_barriers_count: number
  weight: number
  step_free_blocked?: boolean
  traffic_weight?: number
}

export type NetworkFeature =
  | { type: 'Feature'; geometry: GeoJsonPoint; properties: NodeProps }
  | { type: 'Feature'; geometry: GeoJsonLine; properties: EdgeProps }

export interface NetworkCollection {
  type: 'FeatureCollection'
  features: NetworkFeature[]
  meta: { nodes: number; edges: number; step_free_edges: number; generated_at: string }
}

export interface RouteStep {
  index: number
  action: string
  instruction: string
  road_name?: string
  kind?: string
  distance_m: number
  cumulative_m: number
  heading_deg?: number | null
  compass?: string | null
  is_step_free: boolean
  cautions: RouteCaution[]
  to_node?: string
}

export interface RouteCaution {
  type: string
  barrier_id: number
  category: string
  label: string
  severity: number
  distance_m: number
  at_distance_m?: number
  message: string
}

export interface RouteWarning {
  code: string
  message: string
  severity: 'info' | 'medium' | 'high' | 'critical'
  barrier_id?: number
  distance_m?: number
}

export interface RouteSummary {
  accessibility_grade: 'step_free' | 'step_free_with_caution' | 'not_step_free' | 'standard'
  max_incline_pct: number
  min_width_m: number | null
  step_free_segments: number
  total_segments: number
  barrier_count: number
}

export interface RoutePlan {
  found: boolean
  algorithm?: string
  wheelchair_accessible: boolean
  degraded: boolean
  distance_m: number
  distance_text?: string
  duration_s: number
  duration_min: number
  duration_text?: string
  speed_mps?: number
  geojson?: { type: 'Feature'; geometry: GeoJsonLine; properties: Record<string, unknown> }
  coordinates: [number, number][] // [lng, lat] pairs (GeoJSON order)
  steps: RouteStep[]
  segments: {
    edge_id: string
    name?: string
    kind?: string
    distance_m: number
    is_step_free: boolean
    width_m?: number | null
    incline_pct?: number | null
    active_barriers_count: number
    weight?: number | null
  }[]
  warnings: RouteWarning[]
  barriers_on_route: Barrier[]
  node_path: string[]
  edge_path: string[]
  summary?: RouteSummary
  reason?: string
  message?: string
  blocked_edges?: string[]
}

export interface Detection {
  category: string
  confidence: number
  bbox: { x: number; y: number; width: number; height: number }
  source: string
  rationale: string
}

export interface PrivacyReport {
  faces_redacted: number
  plates_redacted: number
  other_redacted: number
  total_redactions: number
  exif_stripped: boolean
  engine: string
  regions: { kind: string; box: number[]; method: string }[]
}

export interface CVResult {
  category: BarrierCategory
  confidence: number
  engine: string
  detections: Detection[]
  privacy: PrivacyReport
  quality: Record<string, unknown>
  image_size: { width: number; height: number }
  sha256?: string
  features: Record<string, number>
  notes: string[]
  auto_verify_threshold: number
  would_auto_verify: boolean
}

export interface ReportResponse {
  action: 'created' | 'confirmed'
  message: string
  barrier: Barrier
  cv: CVResult
  analysis: {
    category: string
    label: string
    confidence: number
    engine: string
    would_auto_verify: boolean
    notes: string[]
    counts: { faces: number; plates: number }
  }
  privacy: PrivacyReport
  image: { image_path: string; thumbnail_path: string; absolute_path?: string }
  edge: { id: string; name: string; kind: string; is_step_free: boolean; active_barriers_count: number; weight: number } | null
  ticket: Ticket | null
  merged_with: number | null
  dedupe: {
    checked_radius_m: number
    merged: boolean
    duplicate_distance_m?: number
    promoted_to_verified?: boolean
    off_network: boolean
    snap_distance_m: number
  }
  auto_verify: {
    threshold: number
    confirmations_needed: number
    verified_now: boolean
  }
}

export interface Preset {
  node_id: string
  label: string
  category?: string
  icon?: string
  note?: string
  name?: string
  latitude: number
  longitude: number
  has_elevator: boolean
  is_step_free: boolean
  campus_zone?: string | null
}

export interface Bounds {
  min_latitude: number
  max_latitude: number
  min_longitude: number
  max_longitude: number
  center_latitude: number
  center_longitude: number
}

export interface Ticket {
  id: number
  code: string
  barrier_id: number | null
  title: string
  detail: string | null
  priority: TicketPriority
  status: TicketStatus
  assigned_team: string
  impact_score: number
  edge_id: string | null
  sla_hours: number
  location_name: string | null
  created_at: string | null
  updated_at: string | null
  resolved_at: string | null
  age_hours: number
  breach_risk: number
  latitude: number | null
  longitude: number | null
  category: BarrierCategory | null
  category_label: string | null
  color: string | null
}

export interface HeatPoint {
  latitude: number
  longitude: number
  intensity: number
  count: number
  active_count: number
  resolved_count: number
  dominant_category: BarrierCategory
  dominant_label: string
  categories: Record<string, number>
  location_name: string | null
  recurring: boolean
}

export interface Hotspot {
  name: string
  latitude: number
  longitude: number
  incidents: number
  active: number
  intensity: number
  dominant_category: BarrierCategory
  dominant_label: string
  recurring: boolean
}

export interface Analytics {
  generated_at: string
  kpis: {
    total_barriers: number
    active_barriers: number
    verified_active: number
    unverified_active: number
    in_progress: number
    resolved_total: number
    created_last_7d: number
    resolved_last_7d: number
    avg_resolution_hours: number | null
    median_resolution_hours: number | null
    avg_confirmations_per_barrier: number
    auto_verified_share: number
    consensus_verified_share: number
    privacy_redactions: number
    faces_redacted: number
    plates_redacted: number
    cv_engine: string
  }
  category_breakdown: {
    category: BarrierCategory
    label: string
    color: string
    severity: number
    total: number
    active: number
    resolved: number
    avg_resolution_hours: number | null
    confirmations: number
    avg_confidence: number
    priority_weight: number
  }[]
  heatmap: HeatPoint[]
  hotspot_zones: Hotspot[]
  resolution_trend: { date: string; created: number; resolved: number }[]
  tickets: {
    total: number
    open: number
    in_progress: number
    resolved: number
    critical_open: number
    breaching_sla: number
    by_priority: Record<string, number>
    by_team: Record<string, number>
    by_status: Record<string, number>
    avg_resolution_hours: number | null
    oldest_open_hours: number | null
  }
  routing_health: {
    network: Record<string, unknown>
    blocked_step_free_edges: string[]
    affected_edges: string[]
    affected_edge_count: number
    affected_edge_share: number
    step_free_coverage: number
    isolated_step_free_zones: number
    nodes: number
    algorithm?: string
  }
  recent_reports: Barrier[]
  status_mix: Record<string, number>
}

export interface Overview {
  app: string
  version: string
  database: string
  graph: {
    nodes: number
    edges: number
    step_free_edges: number
    stairs_edges: number
    buildings: number
    lift_nodes: number
    entrances: number
    barrier_severed_edges: number
    algorithm: string
    speed_mps: { walk: number; wheelchair: number }
  }
  cv: { engine: string; opencv_available: boolean; hint: string }
  presets: Preset[]
  bounds: Bounds
  formula: string
  policies: {
    auto_verify_confidence: number
    consensus_confirmations: number
    duplicate_radius_m: number
  }
}

export interface User {
  id: number
  email: string
  full_name: string
  role: 'student' | 'staff' | 'admin'
}

export interface DemoAccount {
  email: string
  password: string
  role: string
  label: string
}

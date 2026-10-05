/**
 * Ghost Space contracts - mirrors backend/app/schemas/space.py.
 *
 * Kept in its own module so the existing barrier/routing types stay untouched.
 */

export type BookingStatus =
  | 'active'
  | 'checked_in'
  | 'ghost_released'
  | 'reclaimed'
  | 'completed'
  | 'cancelled'

export type OrganizerType = 'faculty' | 'club' | 'student_group' | 'admin'

export type BoardState =
  | 'occupied'
  | 'booked_empty'
  | 'ghost_released'
  | 'reclaimed'
  | 'upcoming'

export interface Room {
  id: string
  name: string
  building: string
  floor: string
  capacity: number
  node_id: string
  is_step_free_access: boolean
  has_accessible_features: boolean
  power_kw: number
  accessible_notes: string | null
}

export interface RoomsResponse {
  total: number
  step_free_count: number
  buildings: string[]
  rooms: Room[]
  energy_note: string
}

export interface Booking {
  id: number
  room_id: string
  organizer_type: OrganizerType
  title: string
  start_ts: string | null
  end_ts: string | null
  expected_attendees: number
  status: BookingStatus
  release_reason: string | null
  released_at: string | null
  reclaimed_at: string | null
}

export interface BoardBooking extends Booking {
  headcount: number
  state: BoardState
  probability: number
}

export interface BoardRoom extends Room {
  bookings: BoardBooking[]
}

export interface LegendItem {
  state: BoardState
  label: string
  color: string
}

export interface DemoClock {
  mode: 'live' | 'demo'
  speed: number
  base: string
  offset_seconds: number
  playing: boolean
  now: string
  demo_date: string
  weekday: number
  hour: number
  label: string
}

export interface Board {
  date: string
  now: string
  clock: DemoClock
  rooms: BoardRoom[]
  legend: LegendItem[]
  simulated: boolean
  simulation_note: string
}

export interface EvidenceItem {
  kind: string
  label: string
  value: number
  detail: string
  source_cell?: string | null
}

export interface Explanation {
  decision: string
  probability: number | null
  evidence: EvidenceItem[]
  constraints_applied: string[] | Record<string, unknown>
  timestamp: string
  method?: string | null
}

export interface MatchedRoom {
  room: Room
  rank: number
  latitude: number
  longitude: number
  straight_line_m: number
  reasons: string[]
  is_step_free_access?: boolean
  has_accessible_features?: boolean
}

export interface ExcludedRoom {
  room: Room
  reason: string
  reason_code: 'capacity' | 'booked' | 'not_step_free' | 'unreachable'
  barrier_id?: number | null
  category?: string | null
  edge_id?: string | null
  status?: string | null
  verified_at?: string | null
  detail?: string | null
}

export interface RoomRequestResponse {
  matched: boolean
  needs_step_free: boolean
  capacity_needed: number
  window: { start: string; end: string }
  origin: { latitude: number; longitude: number; label: string | null }
  results: MatchedRoom[]
  excluded: ExcludedRoom[]
  request_id: number | null
  explanation: Explanation
}

export interface SpaceMetrics {
  generated_at: string
  demo_clock: string
  counts: Record<string, number>
  baseline: {
    label: string
    description: string
    empty_booked_room_hours: number
    wasted_kwh: number
  }
  ghost_space: {
    label: string
    description: string
    empty_booked_room_hours: number
    wasted_kwh: number
    recovered_room_hours: number
    reclaimed_room_hours: number
    kwh_saved: number
  }
  energy: {
    method: string
    is_estimate: boolean
    total_power_kw: number
  }
  releases: {
    decisions: number
    released: number
    true_releases: number
    false_releases: number
    reclaimed_but_was_genuinely_ghost: number
    threshold: number
    grace_minutes: number
    reclaim_window_minutes: number
  }
  release_accuracy: {
    value: number | null
    definition: string
    false_release_rate: number | null
    note: string
    adjusted_value: number | null
  }
  requests: {
    total: number
    fulfilled: number
    unfulfilled: number
    fulfilment_rate: number | null
    step_free_total: number
    step_free_fulfilled: number
    step_free_fulfilment_rate: number | null
  }
  ghost_rate: { value: number | null; definition: string }
}
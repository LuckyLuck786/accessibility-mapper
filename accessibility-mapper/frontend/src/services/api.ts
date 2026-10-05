import axios from 'axios'
import type {
  Analytics,
  Barrier,
  BarrierCollection,
  Booking,
  CategoryInfo,
  CVResult,
  DemoAccount,
  DemoClock,
  NetworkCollection,
  Overview,
  Preset,
  ReportResponse,
  RoomRequestResponse,
  RoomsResponse,
  RoutePlan,
  SpaceMetrics,
  Ticket,
  User,
  Board,
} from '@/types'

export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30_000,
})

const TOKEN_KEY = 'abm.token'
const ADMIN_TOKEN_KEY = 'abm.adminToken'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
  api.defaults.headers.common.Authorization = token ? `Bearer ${token}` : ''
}

if (getToken()) api.defaults.headers.common.Authorization = `Bearer ${getToken()}`

/**
 * The deployment's real admin gate is the `X-Admin-Token` header. It is held
 * in sessionStorage rather than localStorage so it does not outlive the tab,
 * and it is never bundled into the JavaScript - the operator types it in.
 */
export function getAdminToken(): string | null {
  return sessionStorage.getItem(ADMIN_TOKEN_KEY)
}

export function setAdminToken(token: string | null): void {
  if (token) sessionStorage.setItem(ADMIN_TOKEN_KEY, token)
  else sessionStorage.removeItem(ADMIN_TOKEN_KEY)
}

if (getAdminToken()) api.defaults.headers.common['X-Admin-Token'] = getAdminToken() as string

/** Normalise axios errors into something the UI can show a human. */
export function apiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((d) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join('; ')
    }
    return error.message
  }
  return error instanceof Error ? error.message : 'Unexpected error'
}

// ---------------------------------------------------------------------------
// system
// ---------------------------------------------------------------------------
export const fetchOverview = () => api.get<Overview>('/overview').then((r) => r.data)

export const fetchCvStatus = () =>
  api.get<{ engine: string; opencv_available: boolean; hint: string }>('/cv/status').then((r) => r.data)

// ---------------------------------------------------------------------------
// campus + routing
// ---------------------------------------------------------------------------
export const fetchNetwork = () => api.get<NetworkCollection>('/campus/network').then((r) => r.data)

export const fetchPresets = () =>
  api.get<{ presets: Preset[]; bounds: Overview['bounds'] }>('/routes/presets').then((r) => r.data)

export interface PlanRequest {
  start_lat: number
  start_lng: number
  end_lat: number
  end_lng: number
  wheelchair_accessible: boolean
  start_label?: string
  end_label?: string
}

export const planRoute = (payload: PlanRequest) =>
  api.post<RoutePlan>('/routes/plan', payload).then((r) => r.data)

export const fetchAudit = () =>
  api
    .get<{
      unreachable_count: number
      unreachable_facilities: { id: string; name: string; kind: string }[]
      blocked_edges: string[]
      verdict: string
    }>('/campus/accessibility-audit')
    .then((r) => r.data)

// ---------------------------------------------------------------------------
// barriers
// ---------------------------------------------------------------------------
export const fetchActiveBarriers = () =>
  api.get<BarrierCollection>('/barriers/active').then((r) => r.data)

export const fetchCategories = () =>
  api.get<{ categories: CategoryInfo[] }>('/barriers/categories').then((r) => r.data)

export const fetchBarrier = (id: number) => api.get<Barrier>(`/barriers/${id}`).then((r) => r.data)

export interface ReportPayload {
  file: File
  latitude: number
  longitude: number
  category?: string
  description?: string
}

export const reportBarrier = async (payload: ReportPayload): Promise<ReportResponse> => {
  const form = new FormData()
  form.append('file', payload.file)
  form.append('latitude', String(payload.latitude))
  form.append('longitude', String(payload.longitude))
  if (payload.category) form.append('category', payload.category)
  if (payload.description) form.append('description', payload.description)
  const response = await api.post<ReportResponse>('/barriers/report', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return response.data
}

/** Stand-alone CV dry-run is not exposed by the API; the report call returns
 * the full CV payload, so the modal reuses it for the live preview. */
export const confirmBarrier = (id: number, payload: { latitude?: number; longitude?: number; note?: string }) =>
  api
    .post<{ action: string; message: string; barrier: Barrier; promoted_to_verified: boolean }>(
      `/barriers/${id}/confirm`,
      payload,
    )
    .then((r) => r.data)

export const fetchBarrierTimeline = (id: number) =>
  api
    .get<{
      barrier_id: number
      events: { id: number; type: string; actor: string; detail: string | null; created_at: string | null }[]
      confirmations: { id: number; reporter: string; distance_m: number; note: string | null; created_at: string | null }[]
    }>(`/barriers/${id}/timeline`)
    .then((r) => r.data)

// ---------------------------------------------------------------------------
// admin
// ---------------------------------------------------------------------------
export const fetchAnalytics = () => api.get<Analytics>('/admin/analytics').then((r) => r.data)

export const fetchTickets = () =>
  api.get<{ total: number; open: number; items: Ticket[] }>('/admin/tickets').then((r) => r.data)

export const patchTicket = (id: number, payload: { status: string; note?: string; assigned_team?: string }) =>
  api.patch<Ticket>(`/admin/tickets/${id}`, payload).then((r) => r.data)

export const resolveBarrier = (id: number, resolution_note?: string) =>
  api
    .patch<{ action: string; message: string; barrier: Barrier; ticket: Ticket | null }>(
      `/admin/barriers/${id}/resolve`,
      { resolution_note },
    )
    .then((r) => r.data)

export const reopenBarrier = (id: number, reason?: string) =>
  api
    .post<{ action: string; message: string; barrier: Barrier }>(
      `/admin/barriers/${id}/reopen`,
      { resolution_note: reason },
    )
    .then((r) => r.data)

export const verifyBarrier = (id: number, note?: string) =>
  api
    .post<{ action: string; message: string; barrier: Barrier }>(
      `/admin/barriers/${id}/verify?note=${encodeURIComponent(note ?? '')}`,
    )
    .then((r) => r.data)

export const sweepMaintenance = () =>
  api
    .post<{ expired: number; message: string }>('/admin/maintenance/sweep')
    .then((r) => r.data)

export const resetDemo = () =>
  api
    .post<{ status: string; message: string; counts: Record<string, number> }>(
      '/admin/demo/reset',
    )
    .then((r) => r.data)

export const seedDatabase = () =>
  api
    .post<{ status: string; created: boolean; message: string }>('/admin/seed')
    .then((r) => r.data)

// ---------------------------------------------------------------------------
// auth
// ---------------------------------------------------------------------------
export const login = async (email: string, password: string) => {
  const response = await api.post<{ access_token: string; user: User }>('/auth/login', {
    email,
    password,
  })
  setToken(response.data.access_token)
  return response.data.user
}

export const logout = () => {
  setToken(null)
}

export const fetchMe = () => api.get<User>('/auth/me').then((r) => r.data)

export const fetchDemoAccounts = () =>
  api.get<DemoAccount[]>('/auth/demo-accounts').then((r) => r.data)

// ---------------------------------------------------------------------------
// Ghost Space
// ---------------------------------------------------------------------------
export const fetchRooms = () =>
  api.get<RoomsResponse>('/spaces/rooms').then((r) => r.data)

export const fetchBoard = (date?: string) =>
  api
    .get<Board>(`/spaces/board${date ? `?date=${encodeURIComponent(date)}` : ''}`)
    .then((r) => r.data)

export const fetchBookings = (date?: string) =>
  api
    .get<{ date: string; total: number; bookings: Booking[]; simulated: boolean }>(
      `/spaces/bookings${date ? `?date=${encodeURIComponent(date)}` : ''}`,
    )
    .then((r) => r.data)

export interface RoomRequestPayload {
  capacity_needed: number
  start_ts: string
  end_ts: string
  needs_step_free: boolean
  origin_latitude: number
  origin_longitude: number
  origin_label?: string
}

export const requestRoom = (payload: RoomRequestPayload) =>
  api.post<RoomRequestResponse>('/spaces/request', payload).then((r) => r.data)

export const checkIn = (roomId: string, headcount: number, bookingId?: number) =>
  api
    .post<{
      action: string
      booking: Booking | null
      was_false_release: boolean
      timestamp: string
    }>('/spaces/checkin', { room_id: roomId, headcount, booking_id: bookingId })
    .then((r) => r.data)

export const reclaimBooking = (bookingId: number) =>
  api
    .post<{ action: string; message: string; booking: Booking }>(
      `/spaces/bookings/${bookingId}/reclaim`,
      {},
    )
    .then((r) => r.data)

export const fetchSpaceMetrics = () =>
  api.get<SpaceMetrics>('/spaces/metrics').then((r) => r.data)

export const runReleasePass = () =>
  api
    .post<{ evaluated: number; released: unknown[]; held: unknown[] }>('/spaces/release-pass')
    .then((r) => r.data)

export const simulateOccupancy = () =>
  api
    .post<{ signals_created: number; note: string }>('/spaces/simulate', {})
    .then((r) => r.data)

// --- demo clock ----------------------------------------------------------
export const fetchClock = () => api.get<DemoClock>('/demo/clock').then((r) => r.data)

export const setClock = (payload: {
  mode?: 'live' | 'demo'
  speed?: number
  jump_to?: string
  playing?: boolean
  reset?: boolean
}) => api.post<DemoClock>('/demo/clock', payload).then((r) => r.data)

// --- Ghost Space admin overrides ----------------------------------------
export const forceRelease = (bookingId: number, reason?: string) =>
  api
    .post<{ action: string; message: string; booking: Booking }>(
      `/admin/ghost-space/bookings/${bookingId}/force-release`,
      { reason },
    )
    .then((r) => r.data)

export type { Barrier, CVResult, Ticket }

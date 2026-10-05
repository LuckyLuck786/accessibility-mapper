import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Ban, DoorOpen, Info, Undo2, UserCheck } from 'lucide-react'

import {
  apiError,
  checkIn,
  fetchBoard,
  reclaimBooking,
  runReleasePass,
  simulateOccupancy,
} from '@/services/api'
import type { Board, BoardBooking, BoardRoom, BoardState, Explanation } from '@/types/space'
import { Badge, Button, Spinner } from '@/components/ui'
import { ClockControls } from './ClockControls'
import { DecisionDrawer } from './DecisionDrawer'

interface GhostSpaceBoardProps {
  canControl: boolean
  onChanged: () => void
}

const STATE_STYLES: Record<BoardState, string> = {
  occupied: 'bg-emerald-500 text-white',
  booked_empty: 'bg-amber-500 text-white',
  ghost_released: 'bg-violet-600 text-white',
  reclaimed: 'bg-sky-600 text-white',
  upcoming: 'bg-slate-300 text-slate-700',
}

/** Where a booking sits on the 08:00-22:00 strip, as a percentage. */
const DAY_START_HOUR = 8
const DAY_END_HOUR = 22

function positionOf(startIso: string | null, endIso: string | null) {
  if (!startIso || !endIso) return null
  const start = new Date(startIso)
  const end = new Date(endIso)
  const dayStart = new Date(start)
  dayStart.setHours(DAY_START_HOUR, 0, 0, 0)
  const dayEnd = new Date(start)
  dayEnd.setHours(DAY_END_HOUR, 0, 0, 0)
  const span = dayEnd.getTime() - dayStart.getTime()
  const left = ((start.getTime() - dayStart.getTime()) / span) * 100
  const width = ((end.getTime() - start.getTime()) / span) * 100
  if (left < -5 || left > 105) return null
  return { left: Math.max(0, left), width: Math.max(1.2, Math.min(100 - Math.max(0, left), width)) }
}

function timeLabel(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--:--'
}

/**
 * Only used for bookings the engine has not acted on yet, so there is no stored
 * decision to show. It states what is observable and nothing more - it does not
 * pretend to be the engine's reasoning.
 */
function fallbackExplanation(booking: BoardBooking): Explanation {
  return {
    decision: booking.state,
    probability: booking.probability ?? null,
    evidence: [
      {
        kind: 'live_occupancy',
        label: `observed headcount: ${booking.headcount}`,
        value: booking.headcount,
        detail:
          booking.headcount > 0
            ? 'People are in the room, so it is in use.'
            : 'No headcount has been reported since the booking started.',
        source_cell: 'occupancy_signals',
      },
    ],
    constraints_applied: {
      status: booking.status,
      expected_attendees: booking.expected_attendees,
      note: 'No release decision has been applied to this booking yet.',
    },
    timestamp: new Date().toISOString(),
    method: 'Simulated occupancy. Headcount only - no identities are stored.',
  }
}

export function GhostSpaceBoard({ canControl, onChanged }: GhostSpaceBoardProps) {
  const [board, setBoard] = useState<Board | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [drawer, setDrawer] = useState<{ title: string; explanation: Explanation } | null>(null)

  const reload = useCallback(async () => {
    try {
      const data = await fetchBoard()
      setBoard(data)
      setError(null)
    } catch (err) {
      setError(apiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  // While the demo clock is fast-forwarding, keep the board in step with it.
  useEffect(() => {
    if (board?.clock.mode !== 'demo' || !board.clock.playing) return
    const timer = window.setInterval(() => void reload(), 4000)
    return () => window.clearInterval(timer)
  }, [board?.clock.mode, board?.clock.playing, reload])

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true)
      setError(null)
      try {
        await action()
        await reload()
        onChanged()
      } catch (err) {
        setError(apiError(err))
      } finally {
        setBusy(false)
      }
    },
    [reload, onChanged],
  )

  const rooms = useMemo(() => {
    const list = board?.rooms ?? []
    return [...list].sort((a, b) => a.building.localeCompare(b.building) || a.floor.localeCompare(b.floor) || a.name.localeCompare(b.name))
  }, [board])

  const nowPercent = useMemo(() => {
    if (!board) return null
    const now = new Date(board.now)
    const start = new Date(now)
    start.setHours(DAY_START_HOUR, 0, 0, 0)
    const end = new Date(now)
    end.setHours(DAY_END_HOUR, 0, 0, 0)
    const pct = ((now.getTime() - start.getTime()) / (end.getTime() - start.getTime())) * 100
    return pct < 0 || pct > 100 ? null : pct
  }, [board])

  const releasedCount = useMemo(
    () => rooms.flatMap((room) => room.bookings).filter((b) => b.state === 'ghost_released').length,
    [rooms],
  )

  if (loading) return <Spinner label="Loading the Ghost Space board…" />

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-slate-900">Ghost Space board</h2>
          <p className="text-xs text-slate-600">
            {rooms.length} rooms · {releasedCount} ghost-released right now · {timeLabel(board?.now ?? null)} on the demo clock
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canControl && (
            <>
              <Button variant="secondary" disabled={busy} onClick={() => void run(() => simulateOccupancy())}>
                <DoorOpen className="h-4 w-4" aria-hidden /> Simulate occupancy
              </Button>
              <Button disabled={busy} onClick={() => void run(() => runReleasePass())}>
                <Ban className="h-4 w-4" aria-hidden /> Run release pass
              </Button>
            </>
          )}
        </div>
      </div>

      {board?.simulated && (
        <Badge tone="bg-amber-100 text-amber-900 ring-amber-300">
          <AlertTriangle className="h-3 w-3" aria-hidden />
          Simulated data — {board.simulation_note}
        </Badge>
      )}

      <ClockControls clock={board?.clock ?? null} canControl={canControl} onChanged={() => void reload()} />

      {error && (
        <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-800 ring-1 ring-red-300">
          {error}
        </p>
      )}

      {/* legend */}
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        {(board?.legend ?? []).map((item) => (
          <span key={item.state} className="inline-flex items-center gap-1.5 rounded-full bg-white px-2 py-1 font-semibold text-slate-700 ring-1 ring-slate-200">
            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: item.color }} aria-hidden />
            {item.label}
          </span>
        ))}
      </div>

      {/* timeline */}
      <div className="overflow-x-auto rounded-2xl bg-white p-3 ring-1 ring-slate-200">
        <div className="min-w-[600px] sm:min-w-[720px]">
          <div className="relative mb-1 flex justify-between px-[150px] sm:px-[190px] text-[10px] font-semibold text-slate-400">
            {Array.from({ length: (DAY_END_HOUR - DAY_START_HOUR) / 2 + 1 }, (_, index) => (
              <span key={index}>{String(DAY_START_HOUR + index * 2).padStart(2, '0')}:00</span>
            ))}
          </div>

          <div className="relative space-y-1">
            {nowPercent !== null && (
              <div
                className="pointer-events-none absolute inset-y-0 z-10 w-px bg-slate-900/70"
                style={{ left: `calc(150px + (100% - 190px) * ${nowPercent / 100})` }}
                aria-hidden
              />
            )}

            {rooms.map((room) => (
              <RoomRow
                key={room.id}
                room={room}
                canControl={canControl}
                busy={busy}
                onExplain={(booking, explanation) =>
                  setDrawer({ title: `${room.name} — ${timeLabel(booking.start_ts)} booking`, explanation })
                }
                onReclaim={(booking) => void run(() => reclaimBooking(booking.id))}
                onCheckIn={(booking) => void run(() => checkIn(room.id, booking.expected_attendees, booking.id))}
              />
            ))}
          </div>
        </div>
      </div>

      <DecisionDrawer
        open={drawer !== null}
        title={drawer?.title ?? ''}
        explanation={drawer?.explanation ?? null}
        onClose={() => setDrawer(null)}
      />
    </div>
  )
}

interface RoomRowProps {
  room: BoardRoom
  canControl: boolean
  busy: boolean
  onExplain: (booking: BoardBooking, explanation: Explanation) => void
  onReclaim: (booking: BoardBooking) => void
  onCheckIn: (booking: BoardBooking) => void
}

function RoomRow({ room, canControl, busy, onExplain, onReclaim, onCheckIn }: RoomRowProps) {
  const [open, setOpen] = useState(false)

  return (
    <div className="rounded-lg px-1 py-0.5 hover:bg-slate-50">
      <div className="flex items-center gap-2">
        <div className="w-[150px] shrink-0 truncate text-xs sm:w-[180px]">
          <span className="font-semibold text-slate-800">{room.name}</span>
          <span className="block text-[10px] text-slate-500">
            {room.building} · {room.floor} · {room.capacity} seats
            {room.is_step_free_access ? ' · step-free' : ''}
          </span>
        </div>

        <div className="relative h-8 flex-1 rounded-md bg-slate-100">
          {room.bookings.map((booking) => {
            const position = positionOf(booking.start_ts, booking.end_ts)
            if (!position) return null
            return (
              <button
                key={booking.id}
                type="button"
                disabled={!booking.start_ts}
                onClick={() =>
                  booking.start_ts && onExplain(booking, booking.decision ?? fallbackExplanation(booking))
                }
                title={`${booking.title} · ${timeLabel(booking.start_ts)}-${timeLabel(booking.end_ts)}`}
                className={`absolute top-1 flex h-6 items-center overflow-hidden rounded px-1.5 text-left text-[10px] font-semibold transition hover:brightness-95 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600 ${STATE_STYLES[booking.state]}`}
                style={{ left: `${position.left}%`, width: `${position.width}%` }}
              >
                <span className="truncate">
                  {booking.state === 'ghost_released' ? 'RELEASED' : booking.state === 'reclaimed' ? 'RECLAIMED' : booking.expected_attendees}
                </span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="shrink-0 rounded-lg px-1.5 py-1 text-[10px] font-bold text-slate-500 ring-1 ring-slate-200 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
        >
          {open ? 'Hide' : 'Detail'}
        </button>
      </div>

      {open && (
        <ul className="ml-[150px] mt-1 sm:ml-[190px] space-y-1 rounded-lg bg-slate-50 p-2 text-[11px] ring-1 ring-slate-200">
          {room.bookings.length === 0 && <li className="text-slate-500">No bookings this day.</li>}
          {room.bookings.map((booking) => (
            <li key={booking.id} className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-slate-700">
                {timeLabel(booking.start_ts)}-{timeLabel(booking.end_ts)}
              </span>
              <span className={`rounded px-1.5 py-0.5 font-semibold ${STATE_STYLES[booking.state]}`}>{booking.state.replace('_', ' ')}</span>
              <span className="text-slate-600">
                {booking.title} · {booking.organizer_type} · expects {booking.expected_attendees} · headcount {booking.headcount}
              </span>
              {booking.release_reason && (
                <span className="flex w-full items-start gap-1 text-slate-500">
                  <Info className="mt-0.5 h-3 w-3 shrink-0" aria-hidden />
                  {booking.release_reason}
                </span>
              )}
              {canControl && booking.state === 'ghost_released' && (
                <Button variant="secondary" disabled={busy} onClick={() => onReclaim(booking)} className="ml-auto">
                  <Undo2 className="h-3.5 w-3.5" aria-hidden /> Reclaim
                </Button>
              )}
              {canControl && booking.state === 'booked_empty' && (
                <Button variant="secondary" disabled={busy} onClick={() => onCheckIn(booking)} className="ml-auto">
                  <UserCheck className="h-3.5 w-3.5" aria-hidden /> Check in
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

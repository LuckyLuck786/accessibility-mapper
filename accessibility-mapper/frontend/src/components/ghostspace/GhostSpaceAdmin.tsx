import { useCallback, useEffect, useState } from 'react'
import { KeyRound, RotateCcw, ShieldAlert, Unlock } from 'lucide-react'

import {
  apiError,
  fetchBoard,
  forceRelease,
  getAdminToken,
  reclaimBooking,
  resetDemo,
  setAdminToken,
} from '@/services/api'
import type { Board, BoardBooking } from '@/types/space'
import { Badge, Button, Card } from '@/components/ui'

/**
 * Facilities-side Ghost Space controls.
 *
 * The admin token is typed in by the operator and held in sessionStorage; it is
 * never bundled into the JavaScript, so a public deployment cannot leak it by
 * serving the bundle.
 */
export function GhostSpaceAdmin({ onChanged }: { onChanged: () => void }) {
  const [token, setToken] = useState(getAdminToken() ?? '')
  const [authorised, setAuthorised] = useState(Boolean(getAdminToken()))
  const [board, setBoard] = useState<Board | null>(null)
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setBoard(await fetchBoard())
    } catch {
      /* the board is public; a failure here is not worth a scary banner */
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const run = useCallback(
    async (action: () => Promise<unknown>) => {
      setBusy(true)
      setError(null)
      setNotice(null)
      try {
        const result = await action()
        const message = (result as { message?: string } | null)?.message
        setNotice(message ?? 'Done.')
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

  const saveToken = () => {
    const value = token.trim()
    setAdminToken(value || null)
    setAuthorised(Boolean(value))
    setNotice(value ? 'Admin token saved for this tab.' : 'Admin token cleared.')
  }

  const actionable: { room: string; booking: BoardBooking }[] = (board?.rooms ?? []).flatMap((room) =>
    room.bookings
      .filter((booking) => booking.status === 'active' || booking.status === 'ghost_released')
      .map((booking) => ({ room: room.name, booking })),
  )

  return (
    <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[320px_minmax(0,1fr)]">
      <Card className="space-y-3 self-start">
        <div>
          <h2 className="text-base font-bold text-slate-900">Ghost Space admin</h2>
          <p className="text-xs text-slate-600">
            Overrides, demo reset and the clock. Writes need the deployment's admin token.
          </p>
        </div>

        <label className="block text-xs font-semibold text-slate-700">
          Admin token (X-Admin-Token)
          <input
            type="password"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="paste the token"
            autoComplete="off"
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 font-mono text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
          />
        </label>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={saveToken}>
            <KeyRound className="h-4 w-4" aria-hidden /> Save
          </Button>
          {authorised && (
            <Button
              variant="secondary"
              onClick={() => {
                setAdminToken(null)
                setToken('')
                setAuthorised(false)
                setNotice('Admin token cleared.')
              }}
            >
              <Unlock className="h-4 w-4" aria-hidden /> Clear
            </Button>
          )}
        </div>
        {authorised && (
          <Badge tone="bg-emerald-100 text-emerald-800 ring-emerald-300">Token set for this tab</Badge>
        )}

        <hr className="border-slate-200" />

        <div className="space-y-2">
          <h3 className="text-xs font-bold uppercase tracking-wide text-slate-500">Demo controls</h3>
          <Button
            variant="secondary"
            className="w-full justify-center"
            disabled={busy || !authorised}
            onClick={() => void run(() => resetDemo())}
          >
            <RotateCcw className="h-4 w-4" aria-hidden /> Reset the demo day
          </Button>
          <p className="text-[11px] text-slate-500">
            Re-seeds today's bookings and clears every release, reclaim and check-in. Gate it behind the token.
          </p>
        </div>
      </Card>

      <div className="space-y-2">
        {notice && (
          <p role="status" className="rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900 ring-1 ring-emerald-300">
            {notice}
          </p>
        )}
        {error && (
          <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-800 ring-1 ring-red-300">
            {error}
          </p>
        )}

        <Card>
          <h3 className="mb-1 text-sm font-bold text-slate-900">Booking overrides</h3>
          <p className="mb-3 text-[11px] text-slate-600">
            Force-release a room the engine decided to hold, or force a reclaim that has missed its window.
          </p>

          {actionable.length === 0 ? (
            <p className="text-sm text-slate-500">Nothing in flight right now. Advance the demo clock.</p>
          ) : (
            <ul className="max-h-[420px] space-y-1.5 overflow-y-auto">
              {actionable.map(({ room, booking }) => (
                <li
                  key={booking.id}
                  className="flex flex-wrap items-center gap-2 rounded-xl bg-slate-50 px-3 py-2 text-[11px] ring-1 ring-slate-200"
                >
                  <span className="font-semibold text-slate-800">{room}</span>
                  <span className="font-mono text-slate-600">
                    {booking.start_ts ? new Date(booking.start_ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '--'}
                  </span>
                  <span className="rounded bg-white px-1.5 py-0.5 font-semibold text-slate-700 ring-1 ring-slate-300">
                    {booking.status}
                  </span>
                  <span className="text-slate-600">
                    expects {booking.expected_attendees} · headcount {booking.headcount}
                  </span>
                  <span className="ml-auto flex gap-1.5">
                    {booking.status === 'active' && (
                      <Button
                        variant="secondary"
                        disabled={busy || !authorised}
                        onClick={() => void run(() => forceRelease(booking.id, 'admin override'))}
                      >
                        <ShieldAlert className="h-3.5 w-3.5" aria-hidden /> Force release
                      </Button>
                    )}
                    {booking.status === 'ghost_released' && (
                      <Button
                        variant="secondary"
                        disabled={busy || !authorised}
                        onClick={() => void run(() => reclaimBooking(booking.id))}
                      >
                        Force reclaim
                      </Button>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  )
}

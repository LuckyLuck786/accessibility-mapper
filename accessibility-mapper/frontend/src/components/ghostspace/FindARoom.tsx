import { useCallback, useState } from 'react'
import { Accessibility, ChevronDown, ChevronUp, Info, MapPin, Route as RouteIcon, Search } from 'lucide-react'

import { apiError, planRoute, requestRoom } from '@/services/api'
import type { Explanation, RoomRequestResponse } from '@/types/space'
import { Button, Card, Spinner, Toggle } from '@/components/ui'
import { DecisionDrawer } from './DecisionDrawer'

interface FindARoomProps {
  origin: { latitude: number; longitude: number; label: string | null }
  onRoute: (coordinates: [number, number][]) => void
}

const DEFAULT_CAPACITY = 12

function toLocalInput(date: Date): string {
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function minutesFromNow(offset: number): Date {
  return new Date(Date.now() + offset * 60_000)
}

/**
 * The flagship view: a room that is free *and* reachable, right now.
 *
 * The exclusion list is not an error state - it is the most informative part of
 * the answer, because "Health Sciences 302 excluded: lift L2 reported broken,
 * verified 14:05" is exactly the sentence a wheelchair user cannot get from a
 * static room list.
 */
export function FindARoom({ origin, onRoute }: FindARoomProps) {
  const [capacity, setCapacity] = useState(DEFAULT_CAPACITY)
  const [needsStepFree, setNeedsStepFree] = useState(true)
  const [start, setStart] = useState(() => toLocalInput(minutesFromNow(15)))
  const [end, setEnd] = useState(() => toLocalInput(minutesFromNow(105)))
  const [response, setResponse] = useState<RoomRequestResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showExcluded, setShowExcluded] = useState(false)
  const [drawer, setDrawer] = useState<{ title: string; explanation: Explanation } | null>(null)
  const [routing, setRouting] = useState<string | null>(null)

  const submit = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      // The API wants absolute instants; the form speaks local wall-clock time.
      const startDate = new Date()
      const [sh, sm] = start.split(':').map(Number)
      startDate.setHours(sh, sm, 0, 0)
      const endDate = new Date()
      const [eh, em] = end.split(':').map(Number)
      endDate.setHours(eh, em, 0, 0)
      if (endDate <= startDate) endDate.setTime(startDate.getTime() + 60 * 60_000)

      const data = await requestRoom({
        capacity_needed: capacity,
        start_ts: startDate.toISOString(),
        end_ts: endDate.toISOString(),
        needs_step_free: needsStepFree,
        origin_latitude: origin.latitude,
        origin_longitude: origin.longitude,
        origin_label: origin.label ?? undefined,
      })
      setResponse(data)
      setShowExcluded(data.excluded.some((item) => item.reason_code === 'unreachable'))
    } catch (err) {
      setError(apiError(err))
      setResponse(null)
    } finally {
      setLoading(false)
    }
  }, [capacity, start, end, needsStepFree, origin])

  /** Draw the real routed path to the chosen room, respecting step-free mode. */
  const drawRoute = useCallback(
    async (roomId: string, latitude: number, longitude: number) => {
      setRouting(roomId)
      setError(null)
      try {
        const plan = await planRoute({
          start_lat: origin.latitude,
          start_lng: origin.longitude,
          start_label: origin.label ?? undefined,
          end_lat: latitude,
          end_lng: longitude,
          end_label: roomId,
          wheelchair_accessible: needsStepFree,
        })
        if (plan.coordinates?.length) onRoute(plan.coordinates)
        else setError('No route could be drawn to that room.')
      } catch (err) {
        setError(apiError(err))
      } finally {
        setRouting(null)
      }
    },
    [origin, needsStepFree, onRoute],
  )

  const unreachable = response?.excluded.filter((item) => item.reason_code === 'unreachable') ?? []

  return (
    <div className="grid gap-3 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[340px_minmax(0,1fr)]">
      <Card className="space-y-3 self-start">
        <div>
          <h2 className="text-base font-bold text-slate-900">Find a room</h2>
          <p className="text-xs text-slate-600">
            Rooms that are free <em>and</em> reachable right now.
          </p>
        </div>

        <label className="block text-xs font-semibold text-slate-700">
          How many seats?
          <input
            type="number"
            min={1}
            max={500}
            value={capacity}
            onChange={(event) => setCapacity(Math.max(1, Number(event.target.value) || 1))}
            className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
          />
        </label>

        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs font-semibold text-slate-700">
            From
            <input
              type="time"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
            />
          </label>
          <label className="block text-xs font-semibold text-slate-700">
            Until
            <input
              type="time"
              value={end}
              onChange={(event) => setEnd(event.target.value)}
              className="mt-1 w-full rounded-xl border border-slate-300 px-3 py-2 text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
            />
          </label>
        </div>

        <Toggle
          checked={needsStepFree}
          onChange={setNeedsStepFree}
          label="I need step-free access"
          hint="Runs the router with live barrier penalties and excludes rooms with no open step-free route."
        />

        <p className="flex items-center gap-1.5 text-[11px] text-slate-500">
          <MapPin className="h-3.5 w-3.5" aria-hidden />
          Starting from {origin.label ?? 'Red Square'}
        </p>

        <Button className="w-full justify-center" disabled={loading} onClick={() => void submit()}>
          <Search className="h-4 w-4" aria-hidden />
          {loading ? 'Checking…' : 'Find rooms'}
        </Button>

        {error && (
          <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-800 ring-1 ring-red-300">
            {error}
          </p>
        )}

        {response && (
          <div className="rounded-xl bg-slate-50 p-3 text-[11px] leading-relaxed text-slate-700 ring-1 ring-slate-200">
            <p className="font-semibold text-slate-900">
              {response.results.length} room{response.results.length === 1 ? '' : 's'} available ·{' '}
              {response.excluded.length} excluded
            </p>
            <button
              type="button"
              onClick={() => setDrawer({ title: 'How this answer was reached', explanation: response.explanation })}
              className="mt-1 inline-flex items-center gap-1 font-semibold text-campus-700 underline hover:text-campus-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
            >
              <Info className="h-3.5 w-3.5" aria-hidden />
              Why? Show the constraints applied
            </button>
          </div>
        )}
      </Card>

      <div className="space-y-3">
        {loading && <Spinner label="Asking the router…" />}

        {response && !loading && (
          <>
            <section aria-labelledby="matches-heading">
              <h3 id="matches-heading" className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                Best matches
              </h3>
              {response.results.length === 0 ? (
                <Card className="text-sm text-slate-600">
                  No room satisfies every constraint right now. The exclusions below say exactly why.
                </Card>
              ) : (
                <ul className="space-y-2">
                  {response.results.map((item) => (
                    <li key={item.room.id}>
                      <Card className="flex flex-wrap items-start gap-3">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-campus-700 text-xs font-bold text-white">
                              {item.rank}
                            </span>
                            <h4 className="truncate text-sm font-bold text-slate-900">{item.room.name}</h4>
                            {item.room.is_step_free_access && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold text-emerald-800 ring-1 ring-emerald-300">
                                <Accessibility className="h-3 w-3" aria-hidden /> step-free
                              </span>
                            )}
                          </div>
                          <p className="mt-0.5 text-[11px] text-slate-500">
                            {item.room.building} · {item.room.floor} · {item.room.capacity} seats ·{' '}
                            {Math.round(item.straight_line_m)} m away
                          </p>
                          <ul className="mt-1.5 space-y-0.5">
                            {item.reasons.map((reason) => (
                              <li key={reason} className="flex items-start gap-1 text-[11px] text-slate-600">
                                <span aria-hidden>✓</span>
                                {reason}
                              </li>
                            ))}
                          </ul>
                        </div>
                        <Button
                          variant="secondary"
                          disabled={routing === item.room.id}
                          onClick={() => void drawRoute(item.room.id, item.latitude, item.longitude)}
                        >
                          <RouteIcon className="h-4 w-4" aria-hidden />
                          {routing === item.room.id ? 'Routing…' : 'Route'}
                        </Button>
                      </Card>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {response.excluded.length > 0 && (
              <section aria-labelledby="excluded-heading">
                <button
                  type="button"
                  onClick={() => setShowExcluded((value) => !value)}
                  aria-expanded={showExcluded}
                  aria-controls="excluded-list"
                  className="flex w-full items-center justify-between rounded-xl bg-white px-3 py-2 text-left ring-1 ring-slate-200 hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
                >
                  <span className="text-xs font-bold text-slate-800">
                    Excluded ({response.excluded.length})
                    {unreachable.length > 0 && (
                      <span className="ml-2 rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-800">
                        {unreachable.length} unreachable
                      </span>
                    )}
                  </span>
                  {showExcluded ? <ChevronUp className="h-4 w-4" aria-hidden /> : <ChevronDown className="h-4 w-4" aria-hidden />}
                </button>

                {showExcluded && (
                  <ul id="excluded-list" className="mt-2 space-y-1.5">
                    {response.excluded.map((item) => (
                      <li
                        key={item.room.id}
                        className={`rounded-xl px-3 py-2 text-[11px] ring-1 ${
                          item.reason_code === 'unreachable'
                            ? 'bg-red-50 text-red-900 ring-red-200'
                            : 'bg-white text-slate-700 ring-slate-200'
                        }`}
                      >
                        <div className="font-semibold">
                          {item.room.name}{' '}
                          <span className="font-mono text-[10px] opacity-70">({item.reason_code})</span>
                        </div>
                        <p>{item.reason}</p>
                        {item.detail && <p className="mt-0.5 opacity-80">{item.detail}</p>}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}
          </>
        )}
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

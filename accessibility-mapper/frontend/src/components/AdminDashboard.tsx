import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ChevronDown,
  Clock,
  Download,
  Flame,
  Loader2,
  MapPinned,
  RefreshCw,
  ShieldCheck,
  Ticket as TicketIcon,
  Trash2,
  Wrench,
} from 'lucide-react'

import {
  apiError,
  fetchAnalytics,
  fetchAudit,
  fetchTickets,
  patchTicket,
  reopenBarrier,
  resetDemo,
  resolveBarrier,
  sweepMaintenance,
} from '@/services/api'
import type { Analytics, Ticket } from '@/types'
import { Badge, Button, Card, PRIORITY_STYLES, Spinner, StatTile, STATUS_STYLES } from './ui'

interface AdminDashboardProps {
  open: boolean
  onClose: () => void
  onChanged: () => void
  onFocusBarrier: (latitude: number, longitude: number) => void
}

export function AdminDashboard({ open, onClose, onChanged, onFocusBarrier }: AdminDashboardProps) {
  const [analytics, setAnalytics] = useState<Analytics | null>(null)
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [audit, setAudit] = useState<{
    unreachable_count: number
    unreachable_facilities: { id: string; name: string; kind: string }[]
    blocked_edges: string[]
    verdict: string
  } | null>(null)
  const [loading, setLoading] = useState(false)
  const [busyTicket, setBusyTicket] = useState<number | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [analyticsData, ticketData, auditData] = await Promise.all([
        fetchAnalytics(),
        fetchTickets(),
        fetchAudit(),
      ])
      setAnalytics(analyticsData)
      setTickets(ticketData.items)
      setAudit(auditData)
    } catch (loadError) {
      setNotice(apiError(loadError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void reload()
  }, [open, reload])

  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(null), 4200)
    return () => window.clearTimeout(timer)
  }, [notice])

  async function act(action: () => Promise<string>): Promise<void> {
    try {
      setNotice(await action())
      await reload()
      onChanged()
    } catch (actionError) {
      setNotice(apiError(actionError))
    }
  }

  const kpis = analytics?.kpis
  const openTickets = useMemo(
    () => tickets.filter((ticket) => ticket.status !== 'resolved'),
    [tickets],
  )

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[900] overflow-y-auto bg-slate-950/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="admin-title"
    >
      <div className="mx-auto my-4 w-[min(1080px,94vw)] rounded-3xl bg-slate-50 shadow-2xl">
        <header className="sticky top-0 z-10 flex items-center justify-between gap-3 rounded-t-3xl border-b border-slate-200 bg-white/95 px-5 py-3 backdrop-blur">
          <h2 id="admin-title" className="flex items-center gap-2 text-lg font-bold text-slate-900">
            <Wrench className="h-5 w-5 text-campus-600" aria-hidden />
            Facilities dashboard
          </h2>
          <div className="flex items-center gap-2">
            {notice && (
              <p aria-live="polite" className="mr-2 hidden text-sm font-medium text-campus-700 sm:block">
                {notice}
              </p>
            )}
            <Button variant="secondary" onClick={() => void reload()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden /> Refresh
            </Button>
            <Button variant="ghost" onClick={onClose}>
              Close
            </Button>
          </div>
        </header>

        <div className="space-y-4 p-5">
          {loading && !analytics && <Spinner label="Loading dashboard" />}

          {kpis && (
            <section aria-label="Key metrics" className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <StatTile label="Active barriers" value={kpis.active_barriers} tone="text-red-600" />
              <StatTile label="Verified" value={kpis.verified_active} />
              <StatTile label="In progress" value={kpis.in_progress} tone="text-sky-600" />
              <StatTile label="Avg resolution" value={kpis.avg_resolution_hours !== null ? `${kpis.avg_resolution_hours} h` : '—'} />
              <StatTile label="Open tickets" value={analytics?.tickets.open ?? 0} tone="text-orange-600" />
              <StatTile label="Privacy redactions" value={kpis.privacy_redactions} tone="text-emerald-600" sub={`${kpis.cv_engine} engine`} />
            </section>
          )}

          <div className="grid gap-4 lg:grid-cols-2">
            {/* --- ticket queue ------------------------------------- */}
            <Card
              title={
                <span className="flex items-center gap-2">
                  <TicketIcon className="h-4 w-4 text-campus-600" aria-hidden /> Maintenance tickets (
                  {openTickets.length} open)
                </span>
              }
            >
              <ul className="space-y-2">
                {openTickets.map((ticket) => (
                  <TicketRow
                    key={ticket.id}
                    ticket={ticket}
                    busy={busyTicket === ticket.id}
                    onBusy={setBusyTicket}
                    onAct={act}
                    onFocus={() =>
                      ticket.latitude !== null &&
                      ticket.longitude !== null &&
                      onFocusBarrier(ticket.latitude, ticket.longitude)
                    }
                  />
                ))}
                {openTickets.length === 0 && (
                  <li className="rounded-xl bg-emerald-50 px-3 py-4 text-center text-sm font-medium text-emerald-700">
                    🎉 Queue clear - every reported barrier has been resolved.
                  </li>
                )}
              </ul>
            </Card>

            {/* --- right column ------------------------------------- */}
            <div className="space-y-4">
              <Card
                title={
                  <span className="flex items-center gap-2">
                    <Flame className="h-4 w-4 text-orange-500" aria-hidden /> Recurring hotspot zones
                  </span>
                }
              >
                <ol className="space-y-1.5">
                  {(analytics?.hotspot_zones ?? []).map((zone) => (
                    <li key={`${zone.name}-${zone.latitude}`}>
                      <button
                        type="button"
                        onClick={() => onFocusBarrier(zone.latitude, zone.longitude)}
                        className="flex w-full items-center justify-between gap-2 rounded-xl bg-slate-50 px-3 py-2 text-left ring-1 ring-slate-200 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
                      >
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-semibold text-slate-800">{zone.name}</span>
                          <span className="text-xs text-slate-500">
                            {zone.dominant_label}
                            {zone.recurring && <span className="ml-1 font-semibold text-orange-600">· recurring</span>}
                          </span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5">
                          <Badge tone={PRIORITY_STYLES[zone.incidents >= 3 ? 'high' : 'medium']}>
                            {zone.incidents} reports
                          </Badge>
                          <ChevronDown className="h-3.5 w-3.5 rotate-[-90deg] text-slate-400" aria-hidden />
                        </span>
                      </button>
                    </li>
                  ))}
                  {(!analytics || analytics.hotspot_zones.length === 0) && (
                    <li className="text-sm text-slate-500">No incident clusters yet.</li>
                  )}
                </ol>
              </Card>

              {audit && (
                <Card
                  title={
                    <span className="flex items-center gap-2">
                      <ShieldCheck className="h-4 w-4 text-campus-600" aria-hidden /> Step-free reachability
                    </span>
                  }
                >
                  <p className={`text-sm font-semibold ${audit.unreachable_count ? 'text-red-700' : 'text-emerald-700'}`}>
                    {audit.verdict}
                  </p>
                  {audit.unreachable_count > 0 && (
                    <ul className="mt-2 space-y-1 text-xs text-slate-600">
                      {audit.unreachable_facilities.map((facility) => (
                        <li key={facility.id} className="flex items-center gap-1.5">
                          <MapPinned className="h-3.5 w-3.5 text-red-500" aria-hidden />
                          {facility.name}
                          <span className="text-slate-400">({facility.kind})</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <p className="mt-2 text-[11px] text-slate-400">
                    Severed step-free segments: {audit.blocked_edges.join(', ') || 'none'}
                  </p>
                </Card>
              )}

              <Card title="Operations">
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => act(async () => (await sweepMaintenance()).message)}
                  >
                    <Clock className="h-4 w-4" aria-hidden /> Expire stale reports
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() =>
                      act(async () => {
                        const blob = new Blob([JSON.stringify(analytics, null, 2)], { type: 'application/json' })
                        const url = URL.createObjectURL(blob)
                        const anchor = document.createElement('a')
                        anchor.href = url
                        anchor.download = `abm-analytics-${Date.now()}.json`
                        anchor.click()
                        URL.revokeObjectURL(url)
                        return 'Analytics exported as JSON.'
                      })
                    }
                  >
                    <Download className="h-4 w-4" aria-hidden /> Export JSON
                  </Button>
                  <Button
                    variant="danger"
                    onClick={() =>
                      act(async () => {
                        if (!window.confirm('Reset the demo dataset to its scripted state?')) {
                          return 'Reset cancelled.'
                        }
                        return (await resetDemo()).message
                      })
                    }
                  >
                    <Trash2 className="h-4 w-4" aria-hidden /> Reset demo data
                  </Button>
                </div>
              </Card>
            </div>
          </div>

          {/* --- category breakdown --------------------------------- */}
          {analytics && (
            <Card
              title={
                <span className="flex items-center gap-2">
                  <BarChart3 className="h-4 w-4 text-campus-600" aria-hidden /> Barrier breakdown by category
                </span>
              }
            >
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Barrier counts and resolution times by category</caption>
                  <thead>
                    <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                      <th scope="col" className="py-2 pr-3">Category</th>
                      <th scope="col" className="py-2 pr-3">Total</th>
                      <th scope="col" className="py-2 pr-3">Active</th>
                      <th scope="col" className="py-2 pr-3">Resolved</th>
                      <th scope="col" className="py-2 pr-3">Avg fix time</th>
                      <th scope="col" className="py-2 pr-3">Confirmations</th>
                      <th scope="col" className="py-2">Avg confidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.category_breakdown.map((row) => (
                      <tr key={row.category} className="border-b border-slate-100">
                        <td className="py-2 pr-3">
                          <span className="flex items-center gap-2 font-medium text-slate-800">
                            <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: row.color }} />
                            {row.label}
                          </span>
                        </td>
                        <td className="py-2 pr-3 tabular-nums">{row.total}</td>
                        <td className="py-2 pr-3 tabular-nums font-semibold text-red-600">{row.active}</td>
                        <td className="py-2 pr-3 tabular-nums text-emerald-600">{row.resolved}</td>
                        <td className="py-2 pr-3 tabular-nums">{row.avg_resolution_hours !== null ? `${row.avg_resolution_hours} h` : '—'}</td>
                        <td className="py-2 pr-3 tabular-nums">{row.confirmations}</td>
                        <td className="py-2 tabular-nums">{Math.round(row.avg_confidence * 100)}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* --- resolution trend ----------------------------------- */}
          {analytics && (
            <Card
              title={
                <span className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-campus-600" aria-hidden /> 14-day activity
                </span>
              }
            >
              <TrendChart data={analytics.resolution_trend} />
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function TicketRow({
  ticket,
  busy,
  onBusy,
  onAct,
  onFocus,
}: {
  ticket: Ticket
  busy: boolean
  onBusy: (id: number | null) => void
  onAct: (action: () => Promise<string>) => Promise<void>
  onFocus: () => void
}) {
  /** Run an action with this row's busy indicator. */
  function runWithBusy(action: () => Promise<string>): void {
    onBusy(ticket.id)
    onAct(action)
      .then(() => onBusy(null))
      .catch(() => onBusy(null))
  }

  return (
    <li className="rounded-xl bg-white p-3 ring-1 ring-slate-200">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <button type="button" onClick={onFocus} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600">
            <p className="truncate text-sm font-semibold text-slate-900 hover:underline">
              {ticket.code} · {ticket.title}
            </p>
          </button>
          <p className="mt-0.5 text-xs text-slate-500">
            {ticket.assigned_team} · impact {ticket.impact_score}/100 · SLA {ticket.sla_hours} h ·{' '}
            {ticket.breach_risk >= 1 ? (
              <span className="font-bold text-red-600">SLA breached</span>
            ) : (
              `${Math.round(ticket.breach_risk * 100)}% of SLA used`
            )}
          </p>
        </div>
        <span className="flex shrink-0 flex-col items-end gap-1">
          <Badge tone={PRIORITY_STYLES[ticket.priority]}>{ticket.priority}</Badge>
          <Badge tone={STATUS_STYLES[ticket.status]}>{ticket.status.replace('_', ' ')}</Badge>
        </span>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        <Button
          variant="secondary"
          className="px-2 py-1 text-xs"
          disabled={busy || ticket.status === 'in_progress'}
          onClick={() => runWithBusy(async () => {
            const updated = await patchTicket(ticket.id, { status: 'in_progress' })
            return `${updated.code} marked in progress.`
          })}
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Wrench className="h-3.5 w-3.5" aria-hidden />}
          Start work
        </Button>
        <Button
          variant="primary"
          className="px-2 py-1 text-xs"
          disabled={busy}
          onClick={() => runWithBusy(async () => {
            const updated = await patchTicket(ticket.id, { status: 'resolved' })
            return `${updated.code} resolved.`
          })}
        >
          <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Resolve
        </Button>
        {ticket.barrier_id && (
          <>
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              disabled={busy}
              onClick={() => runWithBusy(async () => {
                const response = await reopenBarrier(ticket.barrier_id as number, 'Re-opened from the dashboard')
                return response.message
              })}
            >
              <RefreshCw className="h-3.5 w-3.5" aria-hidden /> Reopen barrier
            </Button>
            <Button
              variant="ghost"
              className="px-2 py-1 text-xs"
              disabled={busy}
              onClick={() => runWithBusy(async () => {
                const response = await resolveBarrier(ticket.barrier_id as number, 'Resolved from the ticket queue')
                return response.message
              })}
            >
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> Resolve barrier
            </Button>
          </>
        )}
      </div>
    </li>
  )
}

/** Tiny inline SVG chart - no chart library needed for a sparkline pair. */
function TrendChart({ data }: { data: { date: string; created: number; resolved: number }[] }) {
  const width = 640
  const height = 120
  const max = Math.max(1, ...data.map((d) => Math.max(d.created, d.resolved)))
  const stepX = width / Math.max(1, data.length - 1)
  const toPath = (key: 'created' | 'resolved') =>
    data
      .map((d, i) => `${i === 0 ? 'M' : 'L'}${(i * stepX).toFixed(1)},${(height - (d[key] / max) * (height - 18)).toFixed(1)}`)
      .join(' ')

  return (
    <figure>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Daily created vs resolved barriers, last 14 days">
        <path d={toPath('created')} fill="none" stroke="#dc2626" strokeWidth="2.5" />
        <path d={toPath('resolved')} fill="none" stroke="#059669" strokeWidth="2.5" />
        {data.map((d, i) => (
          <circle key={d.date} cx={i * stepX} cy={height - (d.resolved / max) * (height - 18)} r="2.5" fill="#059669" />
        ))}
      </svg>
      <figcaption className="mt-1 flex gap-4 text-xs text-slate-500">
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-red-600" /> created</span>
        <span className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-emerald-600" /> resolved</span>
        <span className="ml-auto">{data[0]?.date} → {data[data.length - 1]?.date}</span>
      </figcaption>
    </figure>
  )
}

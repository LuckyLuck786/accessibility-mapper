import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Gauge, RefreshCw } from 'lucide-react'

import { apiError, fetchSpaceMetrics } from '@/services/api'
import type { SpaceMetrics } from '@/types/space'
import { Button, Card, Spinner, StatTile } from '@/components/ui'

interface GhostSpaceMetricsProps {
  refreshToken: number
}

function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${(value * 100).toFixed(1)}%`
}

function num(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

/**
 * BASELINE vs GHOST SPACE.
 *
 * Every number here is computed by the backend from the seeded day and whatever
 * the release engine actually did - there are no constants in this file, and
 * the baseline is the same bookings with the release rule switched off. That is
 * the honest comparison: identical data, one decision rule removed.
 */
export function GhostSpaceMetrics({ refreshToken }: GhostSpaceMetricsProps) {
  const [metrics, setMetrics] = useState<SpaceMetrics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      setMetrics(await fetchSpaceMetrics())
      setError(null)
    } catch (err) {
      setError(apiError(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload, refreshToken])

  if (loading) return <Spinner label="Computing metrics…" />
  if (error) {
    return (
      <Card className="text-sm font-semibold text-red-800">
        {error}
        <Button variant="secondary" className="ml-3" onClick={() => void reload()}>
          <RefreshCw className="h-4 w-4" aria-hidden /> Retry
        </Button>
      </Card>
    )
  }
  if (!metrics) return null

  const { baseline, ghost_space: ghostSpace, releases, release_accuracy: accuracy, requests } = metrics

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-base font-bold text-slate-900">Baseline vs Ghost Space</h2>
          <p className="text-xs text-slate-600">
            Same seeded day, same bookings. The baseline simply never releases anything.
          </p>
        </div>
        <span className="font-mono text-[11px] text-slate-400">
          as of {new Date(metrics.generated_at).toLocaleTimeString()}
        </span>
      </div>

      {metrics.energy.is_estimate && (
        <p className="flex items-start gap-1.5 rounded-xl bg-amber-50 px-3 py-2 text-[11px] font-semibold text-amber-900 ring-1 ring-amber-300">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          Energy figures are an estimate, not metered: {metrics.energy.method}
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <Card>
          <h3 className="mb-1 text-sm font-bold text-slate-900">{baseline.label}</h3>
          <p className="mb-3 text-[11px] text-slate-600">{baseline.description}</p>
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-600">Empty booked room-hours</dt>
              <dd className="font-mono font-bold text-slate-900">{num(baseline.empty_booked_room_hours)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Energy wasted</dt>
              <dd className="font-mono font-bold text-slate-900">{num(baseline.wasted_kwh)} kWh</dd>
            </div>
          </dl>
        </Card>

        <Card className="ring-emerald-300">
          <h3 className="mb-1 text-sm font-bold text-slate-900">{ghostSpace.label}</h3>
          <p className="mb-3 text-[11px] text-slate-600">{ghostSpace.description}</p>
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <dt className="text-slate-600">Recovered room-hours</dt>
              <dd className="font-mono font-bold text-emerald-700">{num(ghostSpace.recovered_room_hours)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Given back after reclaim</dt>
              <dt className="sr-only">Reclaimed room-hours</dt>
              <dd className="font-mono font-bold text-amber-700">{num(ghostSpace.reclaimed_room_hours)}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Energy saved (estimate)</dt>
              <dd className="font-mono font-bold text-emerald-700">{num(ghostSpace.kwh_saved)} kWh</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-slate-600">Empty booked room-hours</dt>
              <dd className="font-mono font-bold text-slate-900">{num(ghostSpace.empty_booked_room_hours)}</dd>
            </div>
          </dl>
        </Card>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Release accuracy"
          value={pct(accuracy.value)}
          sub={`1 − false release rate. ${accuracy.definition}`}
        />
        <StatTile
          label="Requests fulfilled"
          value={`${requests.fulfilled}/${requests.total}`}
          sub={`Step-free fulfilled: ${requests.step_free_fulfilled}/${requests.step_free_total} (${pct(requests.step_free_fulfilment_rate)})`}
        />
        <StatTile
          label="Releases made"
          value={String(releases.released)}
          sub={`of ${releases.decisions} decisions at p ≥ ${releases.threshold}`}
        />
        <StatTile
          label="False releases"
          value={String(releases.false_releases)}
          sub={`${releases.true_releases} were genuinely empty`}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <StatTile label="Ghost rate" value={pct(metrics.ghost_rate.value)} sub={metrics.ghost_rate.definition} />
        <StatTile
          label="Grace period"
          value={`${releases.grace_minutes} min`}
          sub={`Reclaim window ${releases.reclaim_window_minutes} min`}
        />
        <StatTile
          label="Fulfilment rate"
          value={pct(requests.fulfilment_rate)}
          sub="Requests that produced at least one reachable room"
        />
      </div>

      <Card className="flex items-start gap-2 bg-slate-50">
        <Gauge className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" aria-hidden />
        <p className="text-[11px] leading-relaxed text-slate-600">
          {accuracy.note}
          {accuracy.adjusted_value !== null && accuracy.adjusted_value !== undefined && (
            <>
              {' '}
              Counting a check-in after release as a failure gives {pct(accuracy.adjusted_value)}.
            </>
          )}
        </p>
      </Card>
    </div>
  )
}

import { useState } from 'react'
import { Gauge, Pause, Play, RotateCcw, SkipForward } from 'lucide-react'

import { apiError, setClock } from '@/services/api'
import type { DemoClock } from '@/types/space'
import { Button } from '@/components/ui'

interface ClockControlsProps {
  clock: DemoClock | null
  /** False when no admin token is set - writes to the clock are token-gated. */
  canControl: boolean
  onChanged: () => void
}

const SPEEDS = [1, 60, 300, 1800]

/**
 * The whole app reads one clock, so a judge can watch a campus day in about
 * three minutes. Writes are admin-gated server-side; this control is hidden
 * rather than shown-and-failing when no token is present.
 */
export function ClockControls({ clock, canControl, onChanged }: ClockControlsProps) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const apply = async (payload: Parameters<typeof setClock>[0]) => {
    setBusy(true)
    setError(null)
    try {
      await setClock(payload)
      onChanged()
    } catch (err) {
      setError(apiError(err))
    } finally {
      setBusy(false)
    }
  }

  const demoMode = clock?.mode === 'demo'

  if (!clock) return null

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-2xl bg-white p-2.5 ring-1 ring-slate-200">
      <div className="flex items-center gap-2 px-1">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-bold ring-1 ${
            demoMode ? 'bg-violet-50 text-violet-800 ring-violet-300' : 'bg-slate-100 text-slate-600 ring-slate-300'
          }`}
        >
          {demoMode ? 'Demo clock' : 'Live clock'}
        </span>
        <span className="font-mono text-sm font-bold text-slate-900">
          {new Date(clock.now).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </span>
      </div>

      {!canControl ? (
        <p className="px-1 text-[11px] text-slate-500">
          Set an admin token in Admin to drive the demo clock.
        </p>
      ) : (
        <>
          <Button
            variant="secondary"
            disabled={busy || !demoMode}
            onClick={() => void apply({ mode: 'demo', playing: !clock.playing })}
            aria-label={clock.playing ? 'Pause the demo clock' : 'Play the demo clock'}
          >
            {clock.playing ? <Pause className="h-4 w-4" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
            {clock.playing ? 'Pause' : 'Play'}
          </Button>

          <div className="flex items-center gap-1" role="group" aria-label="Clock speed">
            <Gauge className="h-4 w-4 text-slate-400" aria-hidden />
            {SPEEDS.map((speed) => (
              <button
                key={speed}
                type="button"
                disabled={busy}
                aria-pressed={clock.speed === speed}
                onClick={() => void apply({ mode: 'demo', speed })}
                className={`rounded-lg px-2 py-1 font-mono text-xs font-semibold ring-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600 ${
                  clock.speed === speed
                    ? 'bg-campus-700 text-white ring-campus-700'
                    : 'bg-white text-slate-600 ring-slate-300 hover:bg-slate-50'
                }`}
              >
                x{speed}
              </button>
            ))}
          </div>

          <label className="flex items-center gap-1.5 text-[11px] font-semibold text-slate-600">
            <SkipForward className="h-4 w-4 text-slate-400" aria-hidden />
            <span className="sr-only">Jump the demo clock to</span>
            <input
              type="time"
              className="rounded-lg border border-slate-300 px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
              defaultValue={new Date(clock.now).toISOString().slice(11, 16)}
              onChange={(event) => {
                const value = event.target.value
                if (!value) return
                const jumped = new Date(clock.now)
                jumped.setHours(Number(value.slice(0, 2)), Number(value.slice(3, 5)), 0, 0)
                void apply({ mode: 'demo', jump_to: jumped.toISOString() })
              }}
            />
          </label>

          <Button
            variant="secondary"
            disabled={busy}
            onClick={() => void apply({ reset: true })}
            aria-label="Reset the demo clock to the seeded day"
          >
            <RotateCcw className="h-4 w-4" aria-hidden />
            Reset
          </Button>
        </>
      )}

      {error && (
        <p role="alert" className="w-full text-xs font-semibold text-red-700">
          {error}
        </p>
      )}
    </div>
  )
}

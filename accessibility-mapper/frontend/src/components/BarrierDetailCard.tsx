import { useState } from 'react'
import { CheckCircle2, Loader2, MapPin, ShieldCheck, Users } from 'lucide-react'
import { apiError, confirmBarrier } from '@/services/api'
import type { Barrier } from '@/types'
import { Badge, Button, relativeTime, SeverityDots, STATUS_STYLES } from './ui'

interface BarrierDetailCardProps {
  barrier: Barrier
  onClose: () => void
  onUpdated: (barrier: Barrier) => void
}

export function BarrierDetailCard({ barrier, onClose, onUpdated }: BarrierDetailCardProps) {
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleConfirm() {
    setConfirming(true)
    setError(null)
    try {
      const response = await confirmBarrier(barrier.id, {
        latitude: barrier.latitude,
        longitude: barrier.longitude,
        note: 'Confirmed from the map',
      })
      setMessage(response.message)
      onUpdated(response.barrier)
    } catch (confirmError) {
      setError(apiError(confirmError))
    } finally {
      setConfirming(false)
    }
  }

  return (
    <div className="rounded-2xl bg-white p-4 shadow-panel ring-1 ring-slate-200/70">
      <header className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Barrier #{barrier.id}
          </p>
          <h2 className="flex items-center gap-2 text-base font-bold" style={{ color: barrier.color }}>
            {barrier.label}
          </h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close barrier details"
          className="rounded-full p-1 text-slate-400 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
        >
          ✕
        </button>
      </header>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <Badge tone={STATUS_STYLES[barrier.status]}>{barrier.status.replace('_', ' ')}</Badge>
        <Badge>{Math.round(barrier.confidence * 100)}% confidence</Badge>
        <Badge tone="bg-slate-100 text-slate-700 ring-slate-300">{barrier.detection_source}</Badge>
        {barrier.is_hard_block && (
          <Badge tone="bg-red-100 text-red-800 ring-red-300">blocks wheelchair travel</Badge>
        )}
      </div>

      {barrier.description && <p className="mt-2 text-sm text-slate-700">{barrier.description}</p>}

      <dl className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <div className="rounded-xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
          <dt className="font-semibold text-slate-500">Reported</dt>
          <dd className="text-slate-800">
            {relativeTime(barrier.created_at)} by {barrier.reporter_label}
          </dd>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
          <dt className="font-semibold text-slate-500">Confirmations</dt>
          <dd className="flex items-center gap-1.5 text-slate-800">
            <Users className="h-3.5 w-3.5" aria-hidden /> {barrier.confirmations}
            {barrier.status === 'unverified' && (
              <span className="text-slate-500">(needs 2 to verify)</span>
            )}
          </dd>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
          <dt className="font-semibold text-slate-500">Severity</dt>
          <dd className="mt-1">
            <SeverityDots severity={barrier.severity} />
          </dd>
        </div>
        <div className="rounded-xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
          <dt className="font-semibold text-slate-500">Privacy</dt>
          <dd className="text-slate-800">
            {barrier.redacted_faces} face · {barrier.redacted_plates} plate blurred
          </dd>
        </div>
      </dl>

      {barrier.image_url && (
        <img
          src={barrier.image_url}
          alt={`Redacted photo of ${barrier.label}`}
          className="mt-3 max-h-48 w-full rounded-xl object-cover ring-1 ring-slate-200"
        />
      )}

      <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
        <MapPin className="h-3.5 w-3.5" aria-hidden />
        {barrier.latitude.toFixed(5)}, {barrier.longitude.toFixed(5)}
        {barrier.edge_id && <> · on segment {barrier.edge_id}</>}
      </p>

      {message && (
        <p className="mt-2 flex items-center gap-1.5 rounded-xl bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-800">
          <ShieldCheck className="h-4 w-4" aria-hidden /> {message}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 rounded-xl bg-red-50 px-3 py-2 text-xs font-semibold text-red-700">
          {error}
        </p>
      )}

      {barrier.status !== 'resolved' && barrier.status !== 'in_progress' && (
        <Button onClick={handleConfirm} disabled={confirming} className="mt-3 w-full" variant="secondary">
          {confirming ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Sending…
            </>
          ) : (
            <>
              <CheckCircle2 className="h-4 w-4" aria-hidden /> I confirm this is still there
            </>
          )}
        </Button>
      )}
    </div>
  )
}

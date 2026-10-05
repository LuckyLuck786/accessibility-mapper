import { useEffect, useRef, useState } from 'react'
import {
  Camera,
  CheckCircle2,
  EyeOff,
  ImageDown,
  Loader2,
  MapPin,
  ScanSearch,
  ShieldCheck,
  X,
} from 'lucide-react'
import { apiError, reportBarrier } from '@/services/api'
import { useGeolocation } from '@/hooks/useGeolocation'
import type { CategoryInfo, ReportResponse } from '@/types'
import { Badge, Button } from './ui'

export interface ReportModalProps {
  open: boolean
  onClose: () => void
  categories: CategoryInfo[]
  pickedPoint: { latitude: number; longitude: number } | null
  onPickOnMap: () => void
  onReported: (response: ReportResponse) => void
}

export function BarrierReportModal({
  open,
  onClose,
  categories,
  pickedPoint,
  onPickOnMap,
  onReported,
}: ReportModalProps) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [category, setCategory] = useState<string>('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ReportResponse | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const { fix, locate, isLocating } = useGeolocation()

  useEffect(() => {
    if (!open) {
      setFile(null)
      setPreviewUrl(null)
      setCategory('')
      setDescription('')
      setError(null)
      setResult(null)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose, open])

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null)
      return undefined
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  if (!open) return null

  const point = pickedPoint ?? (fix ? { latitude: fix.latitude, longitude: fix.longitude } : null)

  async function handleSubmit() {
    if (!file) {
      setError('Attach a photo of the barrier - the CV pipeline needs it.')
      return
    }
    if (!point) {
      setError('Drop a pin on the map (or use your device location) first.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const response = await reportBarrier({
        file,
        latitude: point.latitude,
        longitude: point.longitude,
        category: category || undefined,
        description: description.trim() || undefined,
      })
      setResult(response)
      onReported(response)
    } catch (submitError) {
      setError(apiError(submitError))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[1000] flex items-end justify-center bg-slate-950/50 p-0 backdrop-blur-sm sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="report-title"
    >
      <div className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-3xl bg-white shadow-2xl sm:rounded-3xl">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-100 bg-white/95 px-5 py-3 backdrop-blur">
          <h2 id="report-title" className="flex items-center gap-2 text-base font-bold text-slate-900">
            <Camera className="h-5 w-5 text-campus-600" aria-hidden />
            Report a barrier
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close dialog"
            className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>

        {result ? (
          <ResultPanel result={result} onClose={onClose} />
        ) : (
          <div className="space-y-4 px-5 py-4">
            {/* --- photo ------------------------------------------------- */}
            <div
              onDragOver={(event) => {
                event.preventDefault()
                setDragOver(true)
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragOver(false)
                const dropped = event.dataTransfer.files?.[0]
                if (dropped && dropped.type.startsWith('image/')) setFile(dropped)
              }}
              className={`rounded-2xl border-2 border-dashed p-4 text-center transition ${
                dragOver ? 'border-campus-500 bg-campus-50' : 'border-slate-300 bg-slate-50'
              }`}
            >
              {previewUrl ? (
                <figure className="space-y-2">
                  <img
                    src={previewUrl}
                    alt="Barrier photo preview (will be redacted before storage)"
                    className="mx-auto max-h-56 rounded-xl object-contain shadow"
                  />
                  <figcaption className="text-xs text-slate-500">{file?.name}</figcaption>
                </figure>
              ) : (
                <div className="py-6">
                  <ImageDown className="mx-auto h-8 w-8 text-slate-400" aria-hidden />
                  <p className="mt-2 text-sm font-medium text-slate-700">
                    Drag & drop a photo, or{' '}
                    <button
                      type="button"
                      className="font-semibold text-campus-700 underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
                      onClick={() => inputRef.current?.click()}
                    >
                      browse
                    </button>
                  </p>
                  <p className="mt-1 text-xs text-slate-500">JPEG or PNG · faces and plates are auto-blurred</p>
                </div>
              )}
              <input
                ref={inputRef}
                type="file"
                accept="image/*"
                capture="environment"
                className="sr-only"
                aria-label="Barrier photo"
                onChange={(event) => {
                  const selected = event.target.files?.[0]
                  if (selected) setFile(selected)
                }}
              />
            </div>

            {/* --- location ---------------------------------------------- */}
            <fieldset className="rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-200">
              <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <MapPin className="mr-1 inline h-3.5 w-3.5" aria-hidden />
                Location
              </legend>
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-slate-800" aria-live="polite">
                  {point
                    ? `${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`
                    : 'No location set'}
                </p>
                <span className="flex gap-1.5">
                  <Button variant="secondary" onClick={onPickOnMap} className="px-2 py-1 text-xs">
                    Pin on map
                  </Button>
                  <Button variant="secondary" onClick={locate} disabled={isLocating} className="px-2 py-1 text-xs">
                    {isLocating ? 'Locating…' : 'Use GPS'}
                  </Button>
                </span>
              </div>
              {pickedPoint && <p className="mt-1 text-xs text-slate-500">Using the pin you dropped on the map.</p>}
            </fieldset>

            {/* --- category ---------------------------------------------- */}
            <fieldset>
              <legend className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                What is blocking the way? <span className="font-normal normal-case">(optional - CV will detect it)</span>
              </legend>
              <div className="grid grid-cols-1 gap-1.5 xs:grid-cols-2">
                {categories.map((info) => (
                  <button
                    key={info.category}
                    type="button"
                    aria-pressed={category === info.category}
                    onClick={() => setCategory((current) => (current === info.category ? '' : info.category))}
                    className={`rounded-xl px-2.5 py-2 text-left text-xs font-semibold ring-1 transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-campus-600 ${
                      category === info.category ? 'text-white' : 'bg-white text-slate-700 ring-slate-200 hover:bg-slate-50'
                    }`}
                    style={category === info.category ? { backgroundColor: info.color } : undefined}
                  >
                    {info.label}
                    {info.step_free_blocking && (
                      <span className="ml-1 font-normal opacity-80">· blocks wheelchairs</span>
                    )}
                  </button>
                ))}
              </div>
            </fieldset>

            {/* --- note --------------------------------------------------- */}
            <label className="block">
              <span className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-slate-500">
                Describe it <span className="font-normal normal-case">(helps the detector & the crew)</span>
              </span>
              <textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={2}
                maxLength={500}
                placeholder="e.g. Two e-scooters parked across the ramp outside the main entrance"
                className="w-full rounded-xl border-slate-300 text-sm shadow-sm focus:border-campus-500 focus:ring-campus-500"
              />
            </label>

            {error && (
              <p role="alert" className="rounded-xl bg-red-50 px-3 py-2 text-sm font-medium text-red-700 ring-1 ring-red-200">
                {error}
              </p>
            )}

            <Button onClick={handleSubmit} disabled={submitting} className="w-full">
              {submitting ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Analysing photo…
                </>
              ) : (
                <>
                  <ScanSearch className="h-4 w-4" aria-hidden /> Run CV analysis & report
                </>
              )}
            </Button>
            <p className="flex items-center justify-center gap-1.5 text-xs text-slate-500">
              <EyeOff className="h-3.5 w-3.5" aria-hidden />
              Privacy first: faces & licence plates are blurred before the image is stored.
            </p>
          </div>
        )}
      </div>
    </div>
  )
}

function ResultPanel({ result, onClose }: { result: ReportResponse; onClose: () => void }) {
  const { barrier, cv, dedupe, privacy, auto_verify: autoVerify } = result
  const detection = cv.detections[0]

  return (
    <div className="space-y-4 px-5 py-4">
      <div className="flex items-start gap-3 rounded-2xl bg-emerald-50 p-3 ring-1 ring-emerald-200">
        <CheckCircle2 className="mt-0.5 h-6 w-6 shrink-0 text-emerald-600" aria-hidden />
        <div>
          <p className="text-sm font-bold text-emerald-900">{result.message}</p>
          <p className="mt-0.5 text-xs text-emerald-700">
            Barrier #{barrier.id} · status <strong>{barrier.status}</strong>
            {dedupe.merged && ` · merged ${dedupe.duplicate_distance_m} m from the original report`}
          </p>
        </div>
      </div>

      {cv && (
        <section aria-label="Computer vision result" className="rounded-2xl ring-1 ring-slate-200">
          <header className="flex items-center justify-between border-b border-slate-100 px-3 py-2">
            <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <ScanSearch className="h-4 w-4 text-campus-600" aria-hidden />
              CV detection result
            </h3>
            <Badge tone="bg-slate-100 text-slate-700 ring-slate-300">{cv.engine}</Badge>
          </header>
          <div className="space-y-3 px-3 py-3">
            <div className="flex items-center justify-between gap-2">
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500">Detected</p>
                <p className="text-base font-bold" style={{ color: barrier.color }}>
                  {barrier.label}
                </p>
              </div>
              <div
                className={`flex h-16 w-16 flex-col items-center justify-center rounded-2xl ring-2 ${
                  cv.confidence >= cv.auto_verify_threshold
                    ? 'bg-emerald-50 text-emerald-700 ring-emerald-300'
                    : 'bg-amber-50 text-amber-700 ring-amber-300'
                }`}
                role="img"
                aria-label={`Confidence ${Math.round(cv.confidence * 100)} percent`}
              >
                <span className="text-xl font-black">{Math.round(cv.confidence * 100)}%</span>
                <span className="text-[9px] font-semibold uppercase">confidence</span>
              </div>
            </div>

            <div
              className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-valuenow={Math.round(cv.confidence * 100)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${Math.round(cv.confidence * 100)}%`,
                  backgroundColor: cv.confidence >= cv.auto_verify_threshold ? '#059669' : '#f59e0b',
                }}
              />
            </div>

            {autoVerify.verified_now ? (
              <p className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
                <ShieldCheck className="h-4 w-4" aria-hidden /> Auto-verified: confidence cleared the{' '}
                {Math.round(autoVerify.threshold * 100)}% threshold. A maintenance ticket is open.
              </p>
            ) : (
              <p className="text-xs text-slate-600">
                Awaiting {Math.max(0, autoVerify.confirmations_needed - barrier.confirmations)} more citizen
                confirmation(s) to auto-verify (confidence below {Math.round(autoVerify.threshold * 100)}%).
              </p>
            )}

            {detection && (
              <p className="rounded-xl bg-slate-50 px-3 py-2 font-mono text-[11px] leading-relaxed text-slate-600">
                {detection.rationale}
              </p>
            )}
          </div>
        </section>
      )}

      <section aria-label="Privacy report" className="rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-200">
        <h3 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
          <EyeOff className="h-4 w-4 text-slate-600" aria-hidden /> Privacy report
        </h3>
        <ul className="mt-1.5 space-y-0.5 text-xs text-slate-600">
          <li>
            {privacy.faces_redacted} face(s) and {privacy.plates_redacted} plate(s) blurred before storage
          </li>
          <li>EXIF metadata (GPS + device identifiers) stripped</li>
          <li>Engine: {privacy.engine}</li>
        </ul>
      </section>

      {result.edge && (
        <section className="rounded-2xl bg-slate-50 p-3 ring-1 ring-slate-200 text-xs text-slate-600">
          <p className="font-semibold text-slate-800">Routed onto the campus graph</p>
          <p className="mt-0.5">
            Segment <strong>{result.edge.name}</strong> ({result.edge.kind},{' '}
            {result.edge.is_step_free ? 'step-free' : 'steps'}). Dynamic weight is now{' '}
            <strong>{result.edge.weight.toFixed(1)}</strong>            {result.edge.active_barriers_count > 0 &&
              ` with ${result.edge.active_barriers_count} active barrier(s) applying the ×10 penalty`}
          </p>
        </section>
      )}

      <Button onClick={onClose} className="w-full">
        Done
      </Button>
    </div>
  )
}

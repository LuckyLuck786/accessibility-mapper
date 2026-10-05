import { X } from 'lucide-react'

import type { Explanation } from '@/types/space'

interface DecisionDrawerProps {
  open: boolean
  title: string
  explanation: Explanation | null
  onClose: () => void
}

function constraintLines(value: Explanation['constraints_applied']): string[] {
  if (Array.isArray(value)) return value.map(String)
  return Object.entries(value).map(([key, raw]) => {
    if (Array.isArray(raw)) {
      return raw.length ? `${key}: ${raw.map(String).join('; ')}` : `${key}: (none)`
    }
    if (raw && typeof raw === 'object') return `${key}: ${JSON.stringify(raw)}`
    return `${key}: ${String(raw)}`
  })
}

/**
 * Every release, exclusion and match decision carries one of these. It is the
 * difference between "the system decided" and "here is exactly why", so it is a
 * dialog rather than a tooltip: a student deciding whether to trust a route
 * deserves the whole argument on screen.
 */
export function DecisionDrawer({ open, title, explanation, onClose }: DecisionDrawerProps) {
  if (!open || !explanation) return null

  const tone =
    explanation.decision === 'release' || explanation.decision === 'matched'
      ? 'text-emerald-700 bg-emerald-50 ring-emerald-200'
      : explanation.decision === 'no_match' || explanation.decision === 'unreachable'
        ? 'text-red-700 bg-red-50 ring-red-200'
        : 'text-amber-800 bg-amber-50 ring-amber-200'

  return (
    <div className="fixed inset-0 z-[1300] flex justify-end" role="presentation">
      <button
        type="button"
        aria-label="Close decision details"
        className="absolute inset-0 bg-slate-900/40"
        onClick={onClose}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative flex h-full w-full max-w-[440px] flex-col overflow-y-auto bg-white shadow-2xl"
      >
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 py-3">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-bold text-slate-900">{title}</h2>
            <p className="text-[11px] text-slate-500">Decision explainer</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-slate-500 hover:bg-slate-100 focus-visible:outline focus-visible:outline-2 focus-visible:outline-campus-600"
          >
            <X className="h-5 w-5" aria-hidden />
          </button>
        </header>

        <div className="space-y-4 px-4 py-4">
          <div className={`inline-flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm font-bold ring-1 ${tone}`}>
            <span className="uppercase tracking-wide">{explanation.decision}</span>
            {explanation.probability !== null && (
              <span className="font-mono text-xs">p_noshow {(explanation.probability * 100).toFixed(0)}%</span>
            )}
          </div>

          <section aria-labelledby="evidence-heading">
            <h3 id="evidence-heading" className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
              Evidence
            </h3>
            {explanation.evidence.length === 0 ? (
              <p className="text-sm text-slate-500">No evidence recorded for this decision.</p>
            ) : (
              <ul className="space-y-2">
                {explanation.evidence.map((item) => (
                  <li key={`${item.kind}-${item.label}`} className="rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-sm font-semibold text-slate-800">{item.label}</span>
                      <span className="font-mono text-xs text-slate-500">{item.value.toFixed(3)}</span>
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-slate-600">{item.detail}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="constraints-heading">
            <h3 id="constraints-heading" className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
              Constraints applied
            </h3>
            <ul className="space-y-1 rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-700 ring-1 ring-slate-200">
              {constraintLines(explanation.constraints_applied).map((line) => (
                <li key={line} className="font-mono">
                  {line}
                </li>
              ))}
            </ul>
          </section>

          {explanation.method && (
            <section aria-labelledby="method-heading">
              <h3 id="method-heading" className="mb-2 text-xs font-bold uppercase tracking-wide text-slate-500">
                Method
              </h3>
              <p className="text-xs leading-relaxed text-slate-600">{explanation.method}</p>
            </section>
          )}

          <p className="text-[11px] text-slate-400">Decided at {new Date(explanation.timestamp).toLocaleTimeString()}</p>
        </div>
      </aside>
    </div>
  )
}

import type { ReactNode } from 'react'

export const STATUS_STYLES: Record<string, string> = {
  unverified: 'bg-amber-100 text-amber-900 ring-amber-300',
  verified: 'bg-emerald-100 text-emerald-900 ring-emerald-300',
  in_progress: 'bg-sky-100 text-sky-900 ring-sky-300',
  resolved: 'bg-slate-100 text-slate-700 ring-slate-300',
  expired: 'bg-slate-100 text-slate-500 ring-slate-200',
  open: 'bg-rose-100 text-rose-900 ring-rose-300',
}

export const PRIORITY_STYLES: Record<string, string> = {
  critical: 'bg-red-600 text-white ring-red-700',
  high: 'bg-orange-500 text-white ring-orange-600',
  medium: 'bg-amber-400 text-amber-950 ring-amber-500',
  low: 'bg-slate-200 text-slate-700 ring-slate-300',
}

export function Badge({
  children,
  tone = 'bg-slate-100 text-slate-800 ring-slate-300',
  className = '',
}: {
  children: ReactNode
  tone?: string
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${tone} ${className}`}
    >
      {children}
    </span>
  )
}

export function SeverityDots({ severity }: { severity: number }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`Severity ${severity} of 5`}>
      {[1, 2, 3, 4, 5].map((level) => (
        <span
          key={level}
          className={`h-1.5 w-1.5 rounded-full ${level <= severity ? 'bg-red-500' : 'bg-slate-300'}`}
        />
      ))}
    </span>
  )
}

export function Card({
  title,
  action,
  children,
  className = '',
}: {
  title?: ReactNode
  action?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={`rounded-2xl bg-white p-4 shadow-panel ring-1 ring-slate-200/70 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (value: boolean) => void
  label: ReactNode
  hint?: string
  disabled?: boolean
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-3 py-1.5">
      <span className="flex-1">
        <span className="block text-sm font-medium text-slate-800">{label}</span>
        {hint && <span className="block text-xs text-slate-500">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={typeof label === 'string' ? label : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-campus-600 ${
          checked ? 'bg-campus-600' : 'bg-slate-300'
        } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
      >
        <span
          aria-hidden
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${
            checked ? 'left-[22px]' : 'left-0.5'
          }`}
        />
      </button>
    </label>
  )
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  type = 'button',
  disabled,
  className = '',
  title,
}: {
  children: ReactNode
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost'
  type?: 'button' | 'submit'
  disabled?: boolean
  className?: string
  title?: string
}) {
  const styles: Record<string, string> = {
    primary: 'bg-campus-600 text-white hover:bg-campus-700 focus-visible:outline-campus-600',
    secondary: 'bg-white text-slate-800 ring-1 ring-slate-300 hover:bg-slate-50 focus-visible:outline-campus-600',
    danger: 'bg-red-600 text-white hover:bg-red-700 focus-visible:outline-red-600',
    ghost: 'bg-transparent text-slate-700 hover:bg-slate-100 focus-visible:outline-campus-600',
  }
  return (
    <button
      type={type}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold shadow-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${styles[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span role="status" aria-live="polite" className="inline-flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-campus-600" />
      {label}…
    </span>
  )
}

export function StatTile({
  label,
  value,
  sub,
  tone = 'text-slate-900',
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: string
}) {
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2 ring-1 ring-slate-200">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`text-xl font-bold leading-tight ${tone}`}>{value}</p>
      {sub && <p className="text-xs text-slate-500">{sub}</p>}
    </div>
  )
}

export function relativeTime(iso: string | null): string {
  if (!iso) return 'unknown'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'unknown'
  const minutes = Math.round((Date.now() - then) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.round(minutes / 60)
  if (hours < 48) return `${hours} h ago`
  return `${Math.round(hours / 24)} d ago`
}

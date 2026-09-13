// 돌봄 관리 공통 UI
export const TYPE_STYLES = [
  'bg-blue-50 text-blue-700 ring-blue-200',
  'bg-amber-50 text-amber-800 ring-amber-200',
  'bg-rose-50 text-rose-700 ring-rose-200',
  'bg-emerald-50 text-emerald-700 ring-emerald-200',
  'bg-violet-50 text-violet-700 ring-violet-200',
  'bg-slate-100 text-slate-700 ring-slate-300',
]

export const LEVELS = {
  high: { label: '우선 관리', pill: 'bg-rose-600 text-white', bar: 'bg-rose-500', soft: 'bg-rose-50 text-rose-700' },
  medium: { label: '주의 관찰', pill: 'bg-amber-500 text-white', bar: 'bg-amber-400', soft: 'bg-amber-50 text-amber-800' },
  low: { label: '정기 관리', pill: 'bg-emerald-600 text-white', bar: 'bg-emerald-500', soft: 'bg-emerald-50 text-emerald-700' },
}

export const SOLUTION_STATUS = {
  draft: { label: '초안 · 검토 필요', cls: 'bg-amber-100 text-amber-800' },
  approved: { label: '승인됨', cls: 'bg-blue-100 text-blue-800' },
  sent: { label: '발송됨', cls: 'bg-emerald-100 text-emerald-800' },
  rejected: { label: '반려', cls: 'bg-gray-200 text-gray-600' },
}

export const TRANSITION = {
  state_change: { label: '유형 변화', cls: 'bg-rose-100 text-rose-700' },
  model_change: { label: '모델 갱신', cls: 'bg-gray-100 text-gray-600' },
}

export function typeIndex(code) {
  const n = parseInt(String(code || '').replace(/\D/g, ''), 10)
  return Number.isFinite(n) ? (n - 1) % TYPE_STYLES.length : 5
}

export function TypeBadge({ code, name, size = 'sm' }) {
  if (!code) return <span className="text-xs text-gray-400">미평가</span>
  const pad = size === 'lg' ? 'px-3 py-1 text-sm' : 'px-2 py-0.5 text-xs'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full ring-1 font-medium ${pad} ${TYPE_STYLES[typeIndex(code)]}`}>
      <span className="font-bold">{code}</span>
      {name && <span className="truncate max-w-[14rem]">{name}</span>}
    </span>
  )
}

export function LevelPill({ level }) {
  const l = LEVELS[level]
  if (!l) return null
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ${l.pill}`}>{l.label}</span>
}

export function ScoreBar({ score, level }) {
  const l = LEVELS[level] || LEVELS.low
  return (
    <div className="flex items-center gap-2 min-w-[7rem]">
      <div className="h-1.5 flex-1 rounded-full bg-gray-100 overflow-hidden">
        <div className={`h-full rounded-full ${l.bar}`} style={{ width: `${Math.min(100, score || 0)}%` }} />
      </div>
      <span className="w-8 text-right text-sm font-semibold tabular-nums text-gray-800">{Math.round(score || 0)}</span>
    </div>
  )
}

export function Card({ title, right, children, className = '' }) {
  return (
    <section className={`bg-white rounded-2xl border border-gray-200 shadow-sm ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-3 border-b border-gray-100">
          <h2 className="text-sm font-bold text-gray-800">{title}</h2>
          {right}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

export function fmtDate(iso) {
  if (!iso) return '-'
  const d = new Date(iso)
  if (isNaN(d)) return iso.slice(0, 10)
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

export function errMsg(e, fallback = '요청에 실패했습니다.') {
  const d = e?.response?.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg).join(', ')
  return fallback
}

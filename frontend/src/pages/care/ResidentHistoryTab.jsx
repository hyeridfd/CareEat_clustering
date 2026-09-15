import { useEffect, useState } from 'react'
import api from '../../lib/api'
import { Card, errMsg } from '../../components/care/CareUI'

const KIND = {
  survey: ['설문', 'bg-slate-100 text-slate-600', 'border-slate-300'],
  assessment: ['평가', 'bg-navy-50 text-navy-700', 'border-navy-400'],
  solution: ['솔루션', 'bg-sky-50 text-sky-700', 'border-sky-400'],
  approval: ['승인', 'bg-emerald-50 text-emerald-700', 'border-emerald-400'],
  notification: ['보호자', 'bg-violet-50 text-violet-700', 'border-violet-400'],
  action: ['돌봄기록', 'bg-amber-50 text-amber-700', 'border-amber-400'],
}
const FILTERS = [['all', '전체'], ['assessment', '평가'], ['solution', '솔루션'],
  ['notification', '보호자'], ['action', '돌봄기록'], ['survey', '설문']]

function stamp(iso) {
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return { day: '', time: '' }
  const p = (n) => String(n).padStart(2, '0')
  return {
    day: `${t.getFullYear()}.${p(t.getMonth() + 1)}.${p(t.getDate())}`,
    time: `${p(t.getHours())}:${p(t.getMinutes())}`,
  }
}

/* 지표 하나짜리 꺾은선 — 계열이 하나뿐이라 범례 없이 제목이 계열을 말한다.
   눈금은 실제 데이터가 닿는 값(최솟값·최댓값)만 적는다. */
function Trend({ t }) {
  const pts = t.points
  const vs = pts.map((p) => p.v)
  const last = vs[vs.length - 1]
  const first = vs[0]
  const lo = Math.min(...vs)
  const hi = Math.max(...vs)
  const pad = (hi - lo) * 0.18 || Math.max(Math.abs(hi) * 0.1, 1)
  const yLo = lo - pad
  const yHi = hi + pad

  const W = 260, H = 74, L = 8, R = 8, T = 10, B = 12
  const x = (i) => (pts.length === 1 ? (W - L - R) / 2 + L : L + (i * (W - L - R)) / (pts.length - 1))
  const y = (v) => T + (1 - (v - yLo) / (yHi - yLo || 1)) * (H - T - B)

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const area = `${line} L${x(pts.length - 1).toFixed(1)},${H - B} L${x(0).toFixed(1)},${H - B} Z`

  const delta = pts.length > 1 ? last - first : null
  const improving = delta == null || delta === 0 ? null : (t.better === 'up' ? delta > 0 : delta < 0)
  const deltaCls = improving == null ? 'text-muted' : improving ? 'text-emerald-600' : 'text-rose-600'
  const digits = t.key === 'bmi' || t.key === 'sat_overall' ? 1 : 0

  return (
    <div className="rounded-xl border border-navy-100 bg-white p-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold text-navy-900">{t.label}</p>
        {delta != null && (
          <span className={`text-[11px] font-semibold tabular-nums ${deltaCls}`}>
            {delta > 0 ? '▲' : delta < 0 ? '▼' : '—'} {Math.abs(delta).toFixed(digits)}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-2xl font-extrabold text-navy-900 tabular-nums leading-none">
        {last.toFixed(digits)}
        <span className="ml-1 text-[11px] font-normal text-muted">{t.unit}</span>
      </p>

      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img"
        aria-label={`${t.label} 추이, 최근 ${last.toFixed(digits)}${t.unit}`}>
        <line x1={L} y1={H - B} x2={W - R} y2={H - B} stroke="#e2e8f0" strokeWidth="1" />
        {pts.length > 1 && <path d={area} fill="#1151b8" fillOpacity="0.07" />}
        {pts.length > 1 && <path d={line} fill="none" stroke="#1151b8" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round" />}
        {pts.map((p, i) => (
          <g key={p.at}>
            <circle cx={x(i)} cy={y(p.v)} r={i === pts.length - 1 ? 4 : 2.5}
              fill={i === pts.length - 1 ? '#1151b8' : '#ffffff'}
              stroke="#1151b8" strokeWidth="1.5" />
            <circle cx={x(i)} cy={y(p.v)} r="10" fill="transparent">
              <title>{`${stamp(p.at).day} · ${p.v.toFixed(digits)}${t.unit}`}</title>
            </circle>
          </g>
        ))}
      </svg>

      <div className="flex justify-between text-[10px] text-muted tabular-nums">
        <span>{stamp(pts[0].at).day}</span>
        <span>{lo.toFixed(digits)}–{hi.toFixed(digits)}{t.unit}</span>
        <span>{stamp(pts[pts.length - 1].at).day}</span>
      </div>
    </div>
  )
}

export default function ResidentHistoryTab({ elderlyId }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('all')

  useEffect(() => {
    api.get(`/ehr/residents/${elderlyId}/history`)
      .then((r) => setD(r.data)).catch((e) => setErr(errMsg(e)))
  }, [elderlyId])

  if (err) return <p className="surface p-6 text-red-700">{err}</p>
  if (!d) return <div className="surface p-12 text-center text-muted">불러오는 중…</div>

  const events = d.events.filter((e) => filter === 'all' || e.kind === filter)

  return (
    <div className="space-y-5">
      {d.trends.length > 0 && (
        <Card title="지표 추이" right={<span className="text-[11px] text-muted">평가 시점 기준</span>}>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {d.trends.map((t) => <Trend key={t.key} t={t} />)}
          </div>
          <p className="mt-3 text-[11px] text-muted">
            점에 마우스를 올리면 그 시점의 값이 나옵니다. 화살표는 첫 평가 대비 변화이며,
            좋아진 방향이면 초록으로 표시합니다.
          </p>
        </Card>
      )}

      <Card
        title="전체 이력"
        right={
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map(([k, l]) => (
              <button key={k} onClick={() => setFilter(k)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-semibold border transition ${
                  filter === k ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-navy-100 text-muted hover:border-navy-200'}`}>
                {l}
              </button>
            ))}
          </div>
        }
      >
        {events.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted">해당하는 이력이 없습니다.</p>
        ) : (
          <ol className="relative">
            {events.map((e, i) => {
              const [label, badgeCls, lineCls] = KIND[e.kind] || KIND.survey
              const s = stamp(e.at)
              return (
                <li key={`${e.at}-${e.kind}-${i}`} className={`relative pl-5 pb-4 border-l-2 ${lineCls} last:pb-0`}>
                  <span className={`absolute -left-[5px] top-1.5 w-2 h-2 rounded-full ${lineCls.replace('border-', 'bg-')}`} />
                  <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                    <span className={`badge ${badgeCls}`}>{label}</span>
                    <span className="text-sm font-semibold text-navy-900">{e.title}</span>
                    <span className="ml-auto text-[11px] text-muted tabular-nums">{s.day} {s.time}</span>
                  </div>
                  {e.detail && <p className="mt-0.5 text-[12px] text-muted">{e.detail}</p>}
                </li>
              )
            })}
          </ol>
        )}
      </Card>
    </div>
  )
}

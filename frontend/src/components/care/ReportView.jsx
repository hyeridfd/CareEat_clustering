import { useState } from 'react'
import { PfmlLogo } from '../brand/Brand'
import { Gauge } from './CareUI'

// 유형 색 (대비 검증 통과 팔레트)
const TYPE_COLORS = ['#1151b8', '#d97706', '#e11d48', '#6d28d9', '#0f9d76', '#475569']
const TONE = {
  good: { chip: 'bg-emerald-50 text-emerald-800 ring-emerald-200', bar: 'bg-emerald-500', mark: '●', word: '양호' },
  warn: { chip: 'bg-amber-50 text-amber-900 ring-amber-200', bar: 'bg-amber-500', mark: '▲', word: '주의' },
  bad: { chip: 'bg-rose-50 text-rose-800 ring-rose-200', bar: 'bg-rose-500', mark: '■', word: '관리 필요' },
  none: { chip: 'bg-slate-50 text-slate-500 ring-slate-200', bar: 'bg-slate-300', mark: '–', word: '미실시' },
}
const MEALS = ['아침', '간식1', '점심', '간식2', '저녁']
const MEAL_LABEL = { 아침: '아침', 간식1: '오전 간식', 점심: '점심', 간식2: '오후 간식', 저녁: '저녁' }

function rateTone(v) {
  if (v == null) return TONE.none
  return v < 50 ? TONE.bad : v < 75 ? TONE.warn : TONE.good
}

function Section({ no, title, sub, children, right }) {
  return (
    <section className="surface p-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3 mb-6">
        <div className="flex items-start gap-3">
          {no && (
            <span className="mt-0.5 flex items-center justify-center w-7 h-7 rounded-lg bg-navy-900 text-white text-[11px] font-extrabold tabular-nums">{no}</span>
          )}
          <div>
            <h2 className="text-lg font-extrabold text-navy-900 leading-snug">{title}</h2>
            {sub && <p className="mt-1 text-xs leading-5 text-muted max-w-xl">{sub}</p>}
          </div>
        </div>
        {right}
      </header>
      {children}
    </section>
  )
}

function Field({ label, value, hint, tone }) {
  const t = tone ? TONE[tone] : null
  return (
    <div className={`rounded-2xl px-4 py-3.5 ${t ? `ring-1 ${t.chip}` : 'bg-navy-50/60'}`}>
      <p className="text-[11px] font-medium opacity-70">{label}</p>
      <p className="mt-1 text-[17px] font-extrabold leading-tight text-navy-900">{value ?? '–'}</p>
      {hint && <p className="mt-0.5 text-[11px] opacity-70">{hint}</p>}
    </div>
  )
}

/* 상태 카드: 단계 + (담당자) 점수 게이지 */
function StatusCard({ s, staff, emoji }) {
  const t = TONE[s.tone] || TONE.none
  const pct = s.value != null && s.scaleMax ? Math.min(100, Math.max(3, (s.value / s.scaleMax) * 100)) : null
  return (
    <div className={`rounded-2xl ring-1 px-4 py-4 ${t.chip}`}>
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold opacity-75">{s.label}</p>
        <span className="text-[10px] opacity-70" aria-hidden>{t.mark}</span>
      </div>
      <p className="mt-1.5 text-[16px] font-extrabold leading-tight">{s.band}</p>
      {s.gauge ? <Gauge g={s.gauge} emoji={emoji} /> : staff && s.value != null && (
        <div className="mt-2.5 h-1.5 rounded-full bg-white/70 overflow-hidden">
          <div className={`h-full rounded-full ${t.bar}`} style={{ width: `${pct ?? 40}%` }} />
        </div>
      )}
      {staff && s.value != null && <p className="mt-1 text-[10px] opacity-70">{s.scale} · {s.value}</p>}
      {staff && s.note && <p className="mt-1 text-[10px] opacity-60">{s.note}</p>}
    </div>
  )
}

/* 가로 비교 막대: 어르신 값 + 시설 평균 표식 */
function CompareRow({ label, value, avg, min = 0, max = 100, unit = '' }) {
  const pct = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))
  const below = avg != null && value < avg
  return (
    <div className="py-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="text-sm font-semibold text-navy-900">{label}</span>
        <span className="ml-auto flex flex-wrap items-baseline justify-end gap-x-2">
          <span className="text-[15px] font-extrabold tabular-nums text-navy-900">{value}{unit}</span>
          {avg != null && (
            <span className={`text-[11px] font-semibold tabular-nums ${below ? 'text-rose-600' : 'text-emerald-700'}`}>
              평균 {avg}{unit} 대비 {below ? '↓' : '↑'} {Math.abs(Math.round((value - avg) * 10) / 10)}
            </span>
          )}
        </span>
      </div>
      <div className="relative h-3.5 rounded-full bg-navy-50">
        <div className="absolute inset-y-0 left-0 rounded-full bg-navy-600" style={{ width: `${pct(value)}%` }} />
        {avg != null && (
          <span className="absolute -top-1 h-[22px] w-[2px] rounded bg-slate-400" title={`시설 평균 ${avg}${unit}`}
            style={{ left: `${pct(avg)}%` }} />
        )}
      </div>
    </div>
  )
}

/* 세로 막대 (px 높이 고정) */
function RateBars({ items, height = 132 }) {
  const list = items || []
  if (!list.length || list.every((x) => x.value == null)) return <p className="text-sm text-muted py-6">기록된 식사 데이터가 없습니다.</p>
  return (
    <div className="flex items-end gap-2.5" style={{ height: height + 46 }}>
      {list.map((x) => {
        const miss = x.value == null
        return (
          <div key={x.label} className="flex-1 flex flex-col items-center justify-end gap-1.5 min-w-0">
            <span className={`text-[11px] font-extrabold tabular-nums ${miss ? 'text-slate-300' : x.value < 50 ? 'text-rose-600' : x.value < 75 ? 'text-amber-700' : 'text-navy-900'}`}>
              {miss ? '–' : `${x.value}%`}
            </span>
            <div className="w-full max-w-[72px] rounded-t-[4px]"
              style={{ height: `${miss ? 5 : Math.max(5, (x.value / 100) * height)}px`,
                background: miss ? '#e2e8f0' : x.value < 50 ? '#e11d48' : x.value < 75 ? '#d97706' : '#1151b8' }} />
            <span className={`text-[11px] truncate w-full text-center ${miss ? 'text-slate-300' : 'text-muted'}`}>{x.label}</span>
          </div>
        )
      })}
    </div>
  )
}

/* 식사 기록표: 일자 × 끼니 (칸을 누르면 그 끼니 메뉴와 영양소가 열린다) */
function MealTable({ log, selected, onSelect }) {
  if (!log?.length) {
    return (
      <p className="text-sm leading-6 text-muted">
        아직 식사 기록이 없습니다. 식사 조사를 입력하면 날짜별로 얼마나 드셨는지 여기에 표시됩니다.
      </p>
    )
  }
  // 조사 기간(5일)은 항상 줄을 만들고, 그날 기록이 아예 없으면 '데이터 없음'으로 표시한다
  const logged = [...new Set(log.map((x) => x.day))]
  const maxDay = Math.max(5, ...logged)
  const days = Array.from({ length: maxDay }, (_, i) => i + 1)
  const cell = (d, m) => log.find((x) => x.day === d && x.meal === m)
  const hasDay = (d) => log.some((x) => x.day === d)
  const isOn = (c) => selected && selected.day === c.day && selected.meal === c.meal
  return (
    <div className="overflow-x-auto -mx-2 px-2">
      <table className="w-full min-w-[560px] border-separate" style={{ borderSpacing: '6px' }}>
        <thead>
          <tr>
            <th className="w-16 text-[11px] font-semibold text-muted text-left">일자</th>
            {MEALS.map((m) => <th key={m} className="text-[11px] font-semibold text-muted">{MEAL_LABEL[m]}</th>)}
          </tr>
        </thead>
        <tbody>
          {days.map((d) => (
            <tr key={d}>
              <th className="text-left text-xs font-bold text-navy-900">{d}일차</th>
              {!hasDay(d) ? (
                <td colSpan={MEALS.length} className="rounded-xl bg-slate-50 text-center text-xs text-slate-400 py-4">
                  데이터 없음
                </td>
              ) : MEALS.map((m) => {
                const c = cell(d, m)
                if (!c) return <td key={m} title="조사 기록 없음" className="rounded-xl bg-slate-50 text-center text-[11px] text-slate-300 py-3">–</td>
                const t = rateTone(c.rate)
                const on = isOn(c)
                return (
                  <td key={m} className="p-0 align-top">
                    <button type="button" onClick={() => onSelect && onSelect(on ? null : c)}
                      className={`w-full rounded-xl ring-1 px-2 py-2.5 text-center transition ${t.chip} ${on ? 'ring-2 ring-navy-600 shadow-sm' : 'hover:brightness-95'}`}>
                      <p className="text-sm font-extrabold tabular-nums leading-none">{c.rate}%</p>
                      <p className="mt-1 text-[10px] opacity-70">{t.word}</p>
                      {c.nut?.energy != null && (
                        <p className="mt-1 text-[10px] font-semibold tabular-nums opacity-80">{Math.round(c.nut.energy)} kcal</p>
                      )}
                      <div className="mt-1.5 flex flex-wrap justify-center gap-0.5">
                        {c.items.slice(0, 6).map((i, k) => (
                          <span key={k} className="w-1.5 h-1.5 rounded-full"
                            style={{ background: i.rate >= 75 ? '#1151b8' : i.rate >= 50 ? '#d97706' : '#e11d48', opacity: 0.85 }} />
                        ))}
                      </div>
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 flex flex-wrap items-center gap-4 text-[11px] text-muted">
        <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-emerald-400" /> 75% 이상</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-amber-400" /> 50–75%</span>
        <span className="inline-flex items-center gap-1.5"><span className="w-2.5 h-2.5 rounded-sm bg-rose-400" /> 50% 미만</span>
        <span>· 점 하나가 반찬 한 가지입니다. 칸을 누르면 그 끼니 메뉴와 영양소가 열립니다.</span>
      </div>
    </div>
  )
}

/* 선택한 끼니의 메뉴와 섭취 영양소 */
function MealDetail({ cell }) {
  if (!cell) {
    return (
      <p className="mt-4 text-xs text-muted rounded-xl bg-slate-50 px-4 py-3">
        위 표에서 칸을 누르면 그 끼니에 무엇이 나왔고 얼마나 드셨는지, 영양소가 얼마나 들어갔는지 볼 수 있습니다.
      </p>
    )
  }
  const n = cell.nut || {}
  const sums = [['에너지', n.energy, 'kcal', 0], ['단백질', n.protein, 'g', 1], ['탄수화물', n.carb, 'g', 1],
                ['지방', n.fat, 'g', 1], ['식이섬유', n.fiber, 'g', 1], ['나트륨', n.na, 'mg', 0],
                ['칼슘', n.ca, 'mg', 0]].filter((x) => x[1] != null)
  return (
    <div className="mt-4 rounded-2xl ring-1 ring-navy-100 bg-white p-4 md:p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-extrabold text-navy-900">{cell.day}일차 {MEAL_LABEL[cell.meal]} 식단</p>
        <p className="text-xs text-muted">이 끼니 섭취율 <b className="text-navy-900">{cell.rate}%</b></p>
      </div>
      <div className="mt-3 overflow-x-auto -mx-1 px-1">
        <table className="w-full min-w-[420px] text-sm">
          <thead>
            <tr className="text-left text-[11px] text-muted border-b border-navy-100">
              <th className="py-2">구분</th><th className="py-2">메뉴</th>
              <th className="py-2 text-right">배식량</th><th className="py-2 text-right">드신 비율</th>
              <th className="py-2 text-right">에너지</th><th className="py-2 text-right">단백질</th>
            </tr>
          </thead>
          <tbody>
            {(cell.items || []).map((it, i) => (
              <tr key={i} className="border-b border-navy-50 last:border-0">
                <td className="py-2 text-xs text-muted whitespace-nowrap">{it.slot}</td>
                <td className="py-2 font-semibold text-navy-900">{it.name || '—'}</td>
                <td className="py-2 text-right tabular-nums text-gray-600">{it.g} g</td>
                <td className={`py-2 text-right tabular-nums font-semibold ${it.rate >= 75 ? 'text-navy-900' : it.rate >= 50 ? 'text-amber-700' : 'text-rose-600'}`}>{it.rate}%</td>
                <td className="py-2 text-right tabular-nums text-gray-600">{it.nut?.energy != null ? `${Math.round(it.nut.energy)}` : '–'}</td>
                <td className="py-2 text-right tabular-nums text-gray-600">{it.nut?.protein != null ? it.nut.protein.toFixed(1) : '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {sums.length > 0 && (
        <div className="mt-4 grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2">
          {sums.map(([l, v, u, d]) => (
            <div key={l} className="rounded-xl bg-navy-50/70 px-3 py-2">
              <p className="text-[10px] text-muted">{l}</p>
              <p className="text-sm font-extrabold tabular-nums text-navy-900">{Number(v).toFixed(d)}<span className="ml-0.5 text-[10px] font-normal text-muted">{u}</span></p>
            </div>
          ))}
        </div>
      )}
      <p className="mt-3 text-[11px] text-muted">식단표의 1인 레시피를 배식량과 남긴 양(목측법)으로 환산한 값입니다. 간식은 성분 자료가 없어 빠져 있습니다.</p>
    </div>
  )
}

/* 섭취 영양소: 1일 평균 · 권장 대비 · 끼니별 · 일자별 */
function NutritionBlock({ n, staff }) {
  const fields = n.fields || []
  const fmt = (v, f) => (v == null ? '–' : Number(v).toFixed(f?.digits ?? 1))
  return (
    <>
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {fields.slice(0, 4).map((f) => (
          <div key={f.key} className="rounded-2xl bg-navy-50/70 px-4 py-3">
            <p className="text-[11px] text-muted">하루 평균 {f.label}</p>
            <p className="mt-1 text-xl font-extrabold tabular-nums text-navy-900">
              {fmt(n.avg_day?.[f.key], f)}<span className="ml-1 text-[11px] font-normal text-muted">{f.unit}</span>
            </p>
          </div>
        ))}
      </div>

      {n.targets?.length > 0 && (
        <div className="mt-7">
          {n.partial && (
            <p className="mb-3 text-[11px] rounded-xl bg-amber-50 text-amber-900 px-3 py-2">
              15끼 중 {n.n_meals}끼만 조사돼, 기록된 끼니를 하루 세 끼로 환산한 값입니다.
            </p>
          )}
          <p className="text-xs font-bold text-navy-900 mb-1">권장 섭취 기준 대비</p>
          <p className="text-[11px] text-muted mb-3">
            2020 한국인 영양소 섭취기준(65세 이상) 대비 하루 평균 섭취량입니다. 나트륨은 적을수록 좋습니다.
          </p>
          <div className="space-y-2.5">
            {n.targets.map((t) => (
              <div key={t.key} className="flex items-center gap-3">
                <span className="w-20 shrink-0 text-xs text-gray-700">{t.label}</span>
                <div className="relative h-3 flex-1 rounded-full bg-navy-50 min-w-0">
                  <div className={`absolute inset-y-0 left-0 rounded-full ${TONE[t.band].bar}`}
                    style={{ width: `${Math.max(2, Math.min(100, t.pct))}%` }} />
                  <span className="absolute inset-y-0 w-px bg-slate-400" style={{ left: '100%' }} />
                </div>
                <span className="w-32 shrink-0 text-right text-[11px] tabular-nums text-muted">
                  <b className="text-navy-900">{t.value}</b> / {t.target} {t.unit}
                </span>
                <span className={`w-12 shrink-0 text-right text-xs font-bold tabular-nums ${t.band === 'bad' ? 'text-rose-600' : t.band === 'warn' ? 'text-amber-700' : 'text-emerald-700'}`}>{t.pct}%</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-8 grid lg:grid-cols-2 gap-6">
        <div>
          <p className="text-xs font-bold text-navy-900 mb-3">끼니별 평균</p>
          <NutTable rows={(n.meals || []).map((m) => ({ label: MEAL_LABEL[m.meal] || m.meal, ...m }))} fields={fields} />
        </div>
        <div>
          <p className="text-xs font-bold text-navy-900 mb-3">일자별 섭취</p>
          <NutTable rows={(n.days || []).map((d) => ({ label: `${d.day}일차`, ...d }))} fields={fields}
            footer={staff ? { label: '하루 평균', ...(n.avg_day || {}) } : null} />
        </div>
      </div>
    </>
  )
}

function NutTable({ rows, fields, footer }) {
  if (!rows?.length) return <p className="text-sm text-muted py-4">기록이 없습니다.</p>
  const cols = fields.slice(0, 5)
  const cell = (r, f) => (r[f.key] == null ? '–' : Number(r[f.key]).toFixed(f.digits ?? 1))
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <table className="w-full min-w-[360px] text-sm">
        <thead>
          <tr className="text-left text-[11px] text-muted border-b border-navy-100">
            <th className="py-2">구분</th>
            {cols.map((f) => <th key={f.key} className="py-2 text-right">{f.label}<span className="font-normal"> ({f.unit})</span></th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-navy-50 last:border-0">
              <td className="py-2 font-semibold text-navy-900 whitespace-nowrap">{r.label}</td>
              {cols.map((f) => <td key={f.key} className="py-2 text-right tabular-nums text-gray-700">{cell(r, f)}</td>)}
            </tr>
          ))}
          {footer && (
            <tr className="bg-navy-50/60">
              <td className="py-2 font-bold text-navy-900">{footer.label}</td>
              {cols.map((f) => <td key={f.key} className="py-2 text-right tabular-nums font-bold text-navy-900">{cell(footer, f)}</td>)}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function TypeDonut({ distribution, total }) {
  const R = 54, C = 2 * Math.PI * R
  let offset = 0
  return (
    <div className="flex flex-wrap items-center gap-7">
      <svg viewBox="0 0 140 140" className="w-[132px] h-[132px] shrink-0" role="img" aria-label="시설 내 유형 분포">
        <g transform="translate(70,70) rotate(-90)">
          {distribution.map((d, i) => {
            const frac = total ? d.count / total : 0
            const len = frac * C
            const el = (
              <circle key={d.code} r={R} fill="none" stroke={TYPE_COLORS[i % TYPE_COLORS.length]}
                strokeWidth={d.is_self ? 22 : 14} strokeDasharray={`${Math.max(0, len - 2)} ${C - Math.max(0, len - 2)}`}
                strokeDashoffset={-offset} opacity={d.is_self ? 1 : 0.5} />
            )
            offset += len
            return el
          })}
        </g>
        <text x="70" y="67" textAnchor="middle" style={{ fontSize: 21, fontWeight: 800, fill: '#0a2e6e' }}>{total}</text>
        <text x="70" y="85" textAnchor="middle" style={{ fontSize: 10, fill: '#64748b' }}>명</text>
      </svg>
      <ul className="space-y-2.5 text-sm">
        {distribution.map((d, i) => (
          <li key={d.code} className="flex items-center gap-2.5">
            <span className="w-3 h-3 rounded-sm shrink-0" style={{ background: TYPE_COLORS[i % TYPE_COLORS.length], opacity: d.is_self ? 1 : 0.5 }} />
            <span className={d.is_self ? 'font-bold text-navy-900' : 'text-slate-600'}>{d.name || d.code}</span>
            <span className="text-muted tabular-nums text-xs">{d.count}명</span>
            {d.is_self && <span className="badge bg-navy-600 text-white">우리 어르신</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stars({ value }) {
  if (value == null) return <span className="text-sm text-muted">–</span>
  const full = Math.round(value)
  return (
    <span className="inline-flex items-baseline gap-1.5">
      <span className="text-amber-500 text-[15px] leading-none" aria-hidden>
        {'★'.repeat(full)}<span className="text-slate-200">{'★'.repeat(Math.max(0, 5 - full))}</span>
      </span>
      <span className="text-sm font-extrabold tabular-nums text-navy-900">{value}</span>
    </span>
  )
}

export default function ReportView({ r }) {
  const staff = r.audience === 'staff'
  const [pickedMeal, setPickedMeal] = useState(null)
  const who = res.gender === '여성' ? '👵' : '🧓'
  const res = r.resident
  const sol = r.solution || {}
  const SCALE_MAX = { 'MNA-SF 0–14': 14, 'K-MMSE-2 0–30': 30, 'K-MBI %': 100, 'GDS-SF 0–15': 15,
    '5일 평균 섭취율 %': 100, 'IPAQ MET-분/주': 1500 }
  const statuses = (r.statuses || []).map((s) => ({ ...s, label: s.title || s.label, scaleMax: SCALE_MAX[s.scale] }))
  const alerts = (r.statuses || []).filter((s) => s.tone === 'bad').length
  const watch = (r.statuses || []).filter((s) => s.tone === 'warn').length

  return (
    <div className="space-y-5">
      {/* 표지 */}
      <section className="rounded-2xl bg-navy-grad text-white p-7 md:p-9 relative overflow-hidden">
        <div aria-hidden className="absolute inset-0 opacity-[0.12]"
          style={{ backgroundImage: 'radial-gradient(circle at 25% 15%, #fff 1px, transparent 1px)', backgroundSize: '24px 24px' }} />
        <div className="relative">
          <p className="text-xs font-semibold text-sky-200">{r.facility?.name}</p>
          <h1 className="mt-2 text-2xl md:text-[32px] font-extrabold tracking-tight leading-snug">
            {res.display_name} 어르신<br />건강·식사 돌봄 리포트
          </h1>
          <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-sm text-navy-100/85">
            {res.age != null && <span>{res.age}세 {res.gender}</span>}
            {res.care_grade && <span>장기요양 {res.care_grade}</span>}
            <span>평가일 {r.assessed_on}</span>
            {r.guardian_name && <span>{r.guardian_name}님께</span>}
          </div>

          <div className="mt-7 grid sm:grid-cols-3 gap-3">
            <div className="rounded-2xl bg-white/[0.12] ring-1 ring-white/15 px-4 py-3.5">
              <p className="text-[11px] text-navy-100/70">관리 구분</p>
              <p className="mt-1 font-extrabold leading-snug">{staff ? `${r.type?.code} · ${r.type?.name}` : (r.type?.guardian_label || r.type?.name)}</p>
            </div>
            <div className="rounded-2xl bg-white/[0.12] ring-1 ring-white/15 px-4 py-3.5">
              <p className="text-[11px] text-navy-100/70">식사 섭취율</p>
              <p className="mt-1 text-2xl font-extrabold tabular-nums leading-none">{r.intake?.total ?? '–'}<span className="text-sm">%</span></p>
            </div>
            <div className="rounded-2xl bg-white/[0.12] ring-1 ring-white/15 px-4 py-3.5">
              <p className="text-[11px] text-navy-100/70">{staff ? '돌봄 우선순위' : '살펴볼 항목'}</p>
              <p className="mt-1 font-extrabold leading-snug">
                {staff && r.priority
                  ? `${Math.round(r.priority.score)}점 · ${{ high: '우선 관리', medium: '주의 관찰', low: '정기 관리' }[r.priority.level]}`
                  : `관리 필요 ${alerts}개 · 주의 ${watch}개`}
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* 한눈에 보기 */}
      <Section title="한눈에 보기" sub={staff ? '카드 아래는 사용한 평가 도구와 점수입니다.' : '어르신의 현재 상태를 단계로 정리했습니다.'}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {statuses.map((s) => <StatusCard key={s.key} s={s} staff={staff} emoji={who} />)}
        </div>
      </Section>

      {/* 유형 */}
      <Section title={staff ? '유형 분류' : '어르신의 관리 구분'}
        sub={staff ? `${r.facility?.name} 어르신 ${r.type?.peer_total}명 기준 분포` : '비슷한 상태의 어르신끼리 묶어 돌봄 방향을 정합니다.'}>
        <div className="rounded-2xl bg-navy-50/70 px-5 py-4 mb-6">
          <p className="text-sm font-extrabold text-navy-900">{staff ? `${r.type?.code} · ${r.type?.name}` : (r.type?.guardian_label || r.type?.name)}</p>
          {r.type?.description && <p className="mt-1.5 text-sm leading-6 text-slate-600">{r.type.description}</p>}
        </div>
        <TypeDonut distribution={r.type?.distribution || []} total={r.type?.peer_total || 0} />
      </Section>

      {/* 시설 평균 비교 */}
      {r.comparison?.length > 0 && (
        <Section no="01" title="같은 시설 어르신들과 비교" sub="진한 막대가 어르신, 회색 선이 시설 평균입니다.">
          <div className="divide-y divide-navy-50">
            {r.comparison.map((c) => <CompareRow key={c.label} {...c} value={c.self} avg={c.facility_avg} />)}
          </div>
        </Section>
      )}

      {/* 기본 정보 */}
      <Section no="02" title="기본 정보와 식사 특성">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="식사 형태" value={res.meal_form} />
          <Field label="식사 도움" value={res.eating} />
          <Field label="씹기" value={res.chewing ? '어려움 있음' : '불편 없음'} tone={res.chewing ? 'warn' : null} />
          <Field label="삼키기" value={res.swallowing ? '어려움 있음' : '불편 없음'} tone={res.swallowing ? 'bad' : null} />
          {staff && <Field label="학력" value={res.education} />}
          {staff && <Field label="장기요양등급" value={res.care_grade} />}
        </div>
      </Section>

      {/* 건강 상태 */}
      {(res.diseases?.length > 0 || res.medications?.length > 0) && (
        <Section no="03" title="건강 상태" sub="조사 시점에 기록된 내용입니다.">
          <div className="grid md:grid-cols-2 gap-6">
            <div>
              <p className="text-xs font-semibold text-muted mb-2">보유 질환</p>
              <div className="flex flex-wrap gap-1.5">
                {res.diseases?.length ? res.diseases.map((d) => <span key={d} className="badge bg-navy-50 text-navy-700">{d}</span>)
                  : <span className="text-sm text-muted">기록 없음</span>}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-muted mb-2">복용 약물</p>
              <div className="flex flex-wrap gap-1.5">
                {res.medications?.length ? res.medications.map((d) => <span key={d} className="badge bg-slate-100 text-slate-700">{d}</span>)
                  : <span className="text-sm text-muted">기록 없음</span>}
              </div>
            </div>
          </div>
        </Section>
      )}

      {/* 신체 계측 */}
      <Section no="04" title="신체 계측">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Field label="키" value={r.anthropometry.height ? `${r.anthropometry.height} cm` : null} />
          <Field label="몸무게" value={r.anthropometry.weight ? `${r.anthropometry.weight} kg` : null}
            hint={r.anthropometry.weight_change != null ? `직전 대비 ${r.anthropometry.weight_change > 0 ? '+' : ''}${r.anthropometry.weight_change}kg` : null}
            tone={r.anthropometry.weight_change != null && r.anthropometry.weight_change <= -2 ? 'bad' : null} />
          <Field label="체질량지수" value={r.anthropometry.bmi} hint={r.anthropometry.bmi_band?.label}
            tone={r.anthropometry.bmi_band?.tone === 'none' ? null : r.anthropometry.bmi_band?.tone} />
          <Field label="혈압" value={r.anthropometry.sbp ? `${r.anthropometry.sbp} / ${r.anthropometry.dbp}` : null}
            hint={r.anthropometry.bp_band?.label || 'mmHg'}
            tone={r.anthropometry.bp_band?.tone === 'good' ? null : r.anthropometry.bp_band?.tone} />
          <Field label="식사 섭취율" value={r.intake.total != null ? `${r.intake.total}%` : null} hint={r.intake.band?.label}
            tone={r.intake.band?.tone === 'none' ? null : r.intake.band?.tone} />
        </div>
        {r.anthropometry.bp_gauge?.pos != null && (
          <div className="mt-5 max-w-md">
            <p className="text-[11px] font-semibold text-muted mb-1">혈압 (수축기 기준)</p>
            <Gauge g={r.anthropometry.bp_gauge} emoji={who} />
          </div>
        )}
      </Section>

      {/* 식사 기록 */}
      <Section no="05" title="실제로 드신 양"
        sub={r.intake.days ? `${r.intake.days}일 동안 끼니마다 남긴 양을 기록해 계산했습니다.` : '식사 기록을 바탕으로 계산했습니다.'}>
        {!r.intake.has_nutrition && (
          <p className="mb-5 text-sm rounded-xl bg-amber-50 text-amber-900 px-4 py-3">식사(잔반) 조사가 완료되지 않아 일부는 추정값입니다.</p>
        )}

        <p className="text-xs font-bold text-navy-900 mb-3">날짜별 식사 기록</p>
        <MealTable log={r.intake.log} selected={pickedMeal} onSelect={setPickedMeal} />
        <MealDetail cell={pickedMeal} />

        <div className="mt-8 grid md:grid-cols-2 gap-8">
          <div>
            <p className="text-xs font-bold text-navy-900 mb-3">끼니별 평균</p>
            <RateBars items={r.intake.meals} />
            <p className="mt-2 text-xs text-muted">
              {r.intake.meals.some((m) => m.value == null)
                ? `${r.intake.meals.filter((m) => m.value == null).map((m) => m.label).join('·')} 기록이 아직 없습니다.`
                : r.intake.low_meals?.length ? `${r.intake.low_meals.join(', ')}에 특히 적게 드셨습니다.` : '끼니별로 고르게 드시고 있습니다.'}
            </p>
          </div>
          <div>
            <p className="text-xs font-bold text-navy-900 mb-3">음식 종류별 평균</p>
            <RateBars items={r.intake.components} />
            <p className="mt-2 text-xs text-muted">주찬은 고기·생선·두부 같은 단백질 반찬입니다.</p>
          </div>
        </div>

        {r.intake.prev_total != null && (
          <p className="mt-6 text-sm rounded-xl bg-navy-50/70 px-4 py-3 text-navy-900">
            직전 평가 {r.intake.prev_total}% → 이번 {r.intake.total}%
            <span className={`ml-2 font-bold ${r.intake.total >= r.intake.prev_total ? 'text-emerald-700' : 'text-rose-700'}`}>
              {r.intake.total > r.intake.prev_total ? `${r.intake.total - r.intake.prev_total}%p 증가`
                : r.intake.total < r.intake.prev_total ? `${r.intake.prev_total - r.intake.total}%p 감소` : '변화 없음'}
            </span>
          </p>
        )}
      </Section>

      {/* 섭취 영양소 */}
      {r.nutrition && (
        <Section no="06" title="섭취 영양소"
          sub={`식단표의 메뉴·배식량과 남기신 양을 합쳐 계산한 ${r.nutrition.n_days || ''}일간 섭취량입니다.`}>
          <NutritionBlock n={r.nutrition} staff={staff} />
        </Section>
      )}

      {/* 만족·선호 */}
      <Section no={r.nutrition ? '07' : '06'} title="급식 만족도와 음식 선호">
        <div className="grid md:grid-cols-3 gap-3">
          {[['전반 만족', r.satisfaction.overall], ['양 적절성', r.satisfaction.portion], ['맛·품질', r.satisfaction.quality]].map(([l, v]) => (
            <div key={l} className="rounded-2xl bg-navy-50/60 px-4 py-3.5">
              <p className="text-[11px] text-muted">{l}</p>
              <div className="mt-1.5"><Stars value={v} /></div>
            </div>
          ))}
        </div>
        {r.satisfaction.prefs?.length > 0 && (
          <div className="mt-6">
            <p className="text-xs font-semibold text-muted mb-2">좋아하시는 음식</p>
            <div className="flex flex-wrap gap-1.5">
              {r.satisfaction.prefs.map((p) => <span key={p} className="badge bg-sky-50 text-sky-800">{p}</span>)}
            </div>
          </div>
        )}
        {r.satisfaction.comment && (
          <blockquote className="mt-6 rounded-2xl bg-white ring-1 ring-navy-100 px-5 py-4 text-sm leading-7 text-slate-700">
            “{r.satisfaction.comment}”
            <span className="block mt-1 text-[11px] text-muted">어르신이 남기신 의견</span>
          </blockquote>
        )}
      </Section>

      {/* 돌봄 제안 */}
      <Section title="돌봄 제안" sub={staff ? '규칙 근거를 바탕으로 만든 제안이며, 담당자 승인 후 적용됩니다.' : '시설에서 이렇게 돌봐 드리고 있습니다.'}>
        {!staff && sol.guardian_message && (
          <p className="rounded-2xl bg-navy-50/70 px-5 py-4 text-[15px] leading-7 text-navy-900 whitespace-pre-line">{sol.guardian_message}</p>
        )}
        {staff && sol.summary && <p className="text-[15px] leading-7 text-navy-900">{sol.summary}</p>}

        {sol.actions?.length > 0 && (
          <ol className="mt-5 grid md:grid-cols-2 gap-3">
            {sol.actions.map((a, i) => (
              <li key={i} className="rounded-2xl ring-1 ring-navy-100 p-5 bg-white">
                <div className="flex items-center gap-2">
                  <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-navy-600 text-white text-xs font-bold tabular-nums">{i + 1}</span>
                  <span className="text-xs font-bold text-navy-600">{a.category}</span>
                </div>
                <p className="mt-2.5 text-[15px] leading-7 text-navy-900">{a.action}</p>
                {a.why && <p className="mt-2 text-xs leading-5 text-muted"><b className="text-navy-500">WHY</b> {a.why}</p>}
              </li>
            ))}
          </ol>
        )}

        <div className="mt-6 grid md:grid-cols-2 gap-6">
          {sol.meal_guidance?.length > 0 && (
            <div>
              <p className="text-xs font-bold text-navy-900 mb-2">식사는 이렇게 준비합니다</p>
              <ul className="space-y-1.5">
                {sol.meal_guidance.map((x, i) => (
                  <li key={i} className="flex gap-2 text-sm leading-6 text-slate-700"><span className="text-navy-500">•</span><span>{x}</span></li>
                ))}
              </ul>
            </div>
          )}
          {sol.monitoring?.length > 0 && (
            <div>
              <p className="text-xs font-bold text-navy-900 mb-2">이렇게 지켜보고 있습니다</p>
              <ul className="space-y-1.5">
                {sol.monitoring.map((x, i) => (
                  <li key={i} className="flex gap-2 text-sm leading-6 text-slate-700"><span className="text-navy-500">•</span><span>{x}</span></li>
                ))}
              </ul>
            </div>
          )}
        </div>
        {!sol.actions?.length && !sol.guardian_message && <p className="text-sm text-muted">아직 만들어진 돌봄 계획이 없습니다.</p>}
      </Section>

      {/* 담당자 전용 */}
      {staff && r.priority?.factors?.length > 0 && (
        <Section title="돌봄 우선순위 근거" sub="유형 위험도, 현재 상태, 직전 평가 대비 변화를 더한 값입니다.">
          <ul className="divide-y divide-navy-50">
            {r.priority.factors.map((x) => (
              <li key={x.code} className="flex items-start justify-between gap-3 py-2.5 text-sm">
                <span className="text-slate-700">
                  {x.kind === 'trend' && <span className="mr-1 badge bg-rose-50 text-rose-700">변화</span>}
                  {x.label}{x.value != null && typeof x.value !== 'boolean' && x.value !== 1 ? <span className="text-muted"> · {x.value}</span> : null}
                </span>
                <span className={`shrink-0 text-xs font-extrabold tabular-nums ${x.points ? 'text-navy-900' : 'text-slate-300'}`}>+{x.points}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {staff && r.history?.length > 1 && (
        <Section title="평가 이력">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[440px]">
              <thead><tr className="text-left text-xs text-muted border-b border-navy-100">
                <th className="py-2">평가일</th><th className="py-2">유형</th><th className="py-2 text-right">섭취율</th>
                <th className="py-2 text-right">체중</th><th className="py-2 text-right">영양 점수</th></tr></thead>
              <tbody>
                {r.history.map((h, i) => (
                  <tr key={i} className="border-b border-navy-50 last:border-0">
                    <td className="py-2">{h.created_at}</td><td className="py-2 font-semibold text-navy-900">{h.type_code}</td>
                    <td className="py-2 text-right tabular-nums">{h.intake_total ?? '–'}%</td>
                    <td className="py-2 text-right tabular-nums">{h.weight_kg ?? '–'}kg</td>
                    <td className="py-2 text-right tabular-nums">{h.mna_sf ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* 안내 */}
      <section className="rounded-2xl border border-navy-100 bg-navy-50/40 p-6">
        <p className="text-xs leading-6 text-muted">
          이 리포트는 시설에서 기록한 조사 자료를 바탕으로 만들어졌으며, <b className="text-navy-900">의학적 진단이나 치료 지침이 아닙니다.</b>
          건강에 관한 판단이 필요한 경우 시설 간호 인력 또는 의료진과 상의해 주세요.
          {r.expires_on && <> 이 페이지는 {r.expires_on}까지 열람할 수 있습니다.</>}
        </p>
        <div className="mt-5 flex items-center gap-3">
          <PfmlLogo className="h-7" />
          <span className="text-[11px] leading-4 text-muted">
            서울대학교 농생명공학부<br />정밀식의약솔루션 연구실 · Care-Eat
            {r.model_version && <> · 유형 모델 {r.model_version}</>}
          </span>
        </div>
      </section>
    </div>
  )
}

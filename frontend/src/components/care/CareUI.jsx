import { PixelSprite } from './PixelCrew'
import { useState } from 'react'
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

// 돌봄 우선순위 점수 산출 근거 — '?' 에 마우스를 올리거나(키보드 포커스·터치) 하면 요인별 배점을 보여준다
const FACTOR_UNIT = {
  mna_malnourished: '점', mna_at_risk: '점', intake_very_low: '%', intake_low: '%', protein_dish_low: '%',
  depressive: '점', depressive_mild: '점',
}
const FACTOR_NO_VALUE = new Set(['swallowing', 'chewing', 'eating_full_help', 'eating_partial_help'])

function factorText(x) {
  if (x.code === 'type_risk') return `${x.value} 유형 (${String(x.label || '').replace(/^유형:\s*/, '')})`
  const v = x.value
  if (v == null || v === 1 || typeof v === 'boolean' || FACTOR_NO_VALUE.has(x.code)) return x.label
  return `${x.label} — ${v}${FACTOR_UNIT[x.code] || ''}`
}

export function ScoreHelp({ score, factors }) {
  const [pos, setPos] = useState(null)
  const list = factors || []
  const scored = list.filter((x) => x.points > 0)
  const notes = list.filter((x) => !x.points)
  const sum = scored.reduce((s, x) => s + x.points, 0)
  const open = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const w = 320
    const left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8)
    const up = window.innerHeight - r.bottom < 280
    setPos(up ? { left, bottom: window.innerHeight - r.top + 8, w } : { left, top: r.bottom + 8, w })
  }
  const close = () => setPos(null)
  return (
    <span className="inline-flex" onClick={(e) => e.stopPropagation()}>
      <button type="button" aria-label="점수 산출 근거 보기"
        onMouseEnter={open} onMouseLeave={close} onFocus={open} onBlur={close}
        className="w-4 h-4 shrink-0 rounded-full border border-gray-300 text-[10px] font-bold leading-none text-gray-500 inline-flex items-center justify-center hover:border-blue-400 hover:text-blue-600 focus:outline-none focus:ring-2 focus:ring-blue-200">?</button>
      {pos && (
        <div role="tooltip" style={{ position: 'fixed', left: pos.left, top: pos.top, bottom: pos.bottom, width: pos.w, zIndex: 60 }}
          className="pointer-events-none rounded-lg bg-gray-900 text-white text-xs leading-5 shadow-lg p-3 text-left font-normal">
          <p className="font-semibold mb-1.5">점수 산출 근거</p>
          {scored.length ? (
            <ul className="space-y-1">
              {scored.map((x) => (
                <li key={x.code} className="flex items-start justify-between gap-3">
                  <span className="text-gray-200">
                    {x.kind === 'trend' && <span className="mr-1 text-[10px] rounded bg-rose-500/30 text-rose-100 px-1">변화</span>}
                    {factorText(x)}
                  </span>
                  <span className="shrink-0 font-semibold tabular-nums">+{x.points}점</span>
                </li>
              ))}
            </ul>
          ) : <p className="text-gray-300">해당하는 위험 요인이 없습니다.</p>}
          <div className="mt-2 pt-2 border-t border-white/20 flex justify-between font-semibold">
            <span>합계{sum > 100 ? ` ${sum}점 → 상한 적용` : ''}</span>
            <span className="tabular-nums">{Math.round(score ?? Math.min(100, sum))}점</span>
          </div>
          {notes.map((x) => <p key={x.code} className="mt-1 text-[11px] text-amber-200">참고: {x.label}</p>)}
          <p className="mt-2 text-[11px] text-gray-400">45점 이상 우선 관리 · 20–44점 주의 관찰 · 20점 미만 정기 관리</p>
        </div>
      )}
    </span>
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
  if (e?.code === 'ECONNABORTED') return '응답 시간이 초과됐습니다. 서버에서 작업이 계속되고 있을 수 있으니 잠시 후 새로고침해 보세요.'
  if (typeof d === 'string') return d
  if (Array.isArray(d)) return d.map((x) => x.msg).join(', ')
  return fallback
}

/* 표 정렬 — 머리글을 누르면 오름차순 ⇄ 내림차순.
   useSort 는 정렬 상태와 비교 함수를, SortTh 는 누를 수 있는 머리글을 준다. */
export function useSortState(initialKey = null, initialDir = 'asc') {
  const [sort, setSort] = useState({ key: initialKey, dir: initialDir })
  const toggle = (key) =>
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))
  return [sort, toggle]
}

/* values: 행 → 정렬값(숫자·문자·null). null 은 항상 뒤로 보낸다. */
export function sortRows(rows, sort, values) {
  if (!sort?.key || !values[sort.key]) return rows
  const get = values[sort.key]
  const sign = sort.dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const x = get(a), y = get(b)
    const nx = x === null || x === undefined || x === '', ny = y === null || y === undefined || y === ''
    if (nx && ny) return 0
    if (nx) return 1
    if (ny) return -1
    if (typeof x === 'number' && typeof y === 'number') return (x - y) * sign
    return String(x).localeCompare(String(y), 'ko') * sign
  })
}

export function SortTh({ label, sortKey, sort, onSort, className = '', align = 'left' }) {
  const on = sort?.key === sortKey
  const mark = !on ? '↕' : sort.dir === 'asc' ? '↑' : '↓'
  return (
    <th className={`${className} ${align === 'right' ? 'text-right' : 'text-left'}`}>
      <button type="button" onClick={() => onSort(sortKey)}
        className={`inline-flex items-center gap-1 hover:text-navy-700 ${on ? 'text-navy-700 font-semibold' : ''}`}>
        {label}
        <span className={`text-[10px] ${on ? 'opacity-90' : 'opacity-30'}`}>{mark}</span>
      </button>
    </th>
  )
}

/* 지표 눈금 — 구간(정상/주의/관리 필요)을 색으로 깔고, 눈금 숫자와 어르신 위치를 함께 보여준다.
   점수 체계를 모르는 사람도 "이 정도면 어디쯤"인지 바로 보이게 하는 것이 목적. */
// 단계마다 색조를 달리해 인접 구간이 한 덩어리로 보이지 않게 한다
const SEG_FILL = {
  good: 'bg-emerald-400', good2: 'bg-emerald-200',
  warn: 'bg-amber-400', warn2: 'bg-amber-200',
  bad: 'bg-rose-400', bad2: 'bg-rose-200',
  none: 'bg-slate-200',
}

function tickStyle(pct) {
  if (pct <= 2) return { left: 0, transform: 'none' }
  if (pct >= 98) return { right: 0, left: 'auto', transform: 'none' }
  return { left: `${pct}%`, transform: 'translateX(-50%)' }
}

export function Gauge({ g, emoji = '🧓', compact = false }) {
  if (!g?.segments?.length) return null
  const span = (g.max - g.min) || 1
  const at = (v) => Math.max(0, Math.min(100, ((v - g.min) / span) * 100))
  const ticks = g.ticks || [g.min, ...g.segments.map((s) => s.to)]
  return (
    <div className={`pb-avoid ${compact ? 'mt-1.5' : 'mt-2'}`}>
      {/* 어르신 위치 */}
      <div className="relative h-5">
        {g.pos != null && (
          <span className="absolute -translate-x-1/2 text-[15px] leading-5 select-none"
            style={{ left: `${g.pos}%` }} role="img" aria-label="어르신 위치">{emoji}</span>
        )}
      </div>
      <div className="relative">
        <div className="flex h-2 rounded-full overflow-hidden bg-slate-100">
          {g.segments.map((s, i) => (
            <div key={`${s.label}-${s.to}`}
              className={`${SEG_FILL[s.tone] || SEG_FILL.none} ${i ? 'border-l border-white' : ''}`}
              style={{ width: `${s.width}%` }} title={`${s.label} ${s.from}–${s.to}${g.unit || ''}`} />
          ))}
        </div>
        {g.pos != null && (
          <span className="absolute -top-0.5 h-3 w-[2px] rounded-sm bg-gray-900/70"
            style={{ left: `calc(${g.pos}% - 1px)` }} aria-hidden />
        )}
      </div>
      {/* 눈금 숫자 */}
      <div className="relative h-3.5 mt-0.5">
        {ticks.map((t) => (
          <span key={t} className="absolute text-[9px] leading-3 text-gray-400 tabular-nums" style={tickStyle(at(t))}>{t}</span>
        ))}
      </div>
      {!compact && (
        <div className="flex text-[9px] leading-3 text-gray-400">
          {g.segments.map((s) => (
            <span key={s.label} className="px-0.5 text-center overflow-hidden whitespace-nowrap text-ellipsis"
              style={{ width: `${s.width}%` }} title={`${s.label} ${s.from}–${s.to}`}>{s.label}</span>
          ))}
        </div>
      )}
      <p className="mt-0.5 text-[9px] text-gray-400">
        {g.unit}{g.reverse ? ' · 낮을수록 좋음' : ''}{g.note ? ` · ${g.note}` : ''}
      </p>
    </div>
  )
}

/* [2026-11-24] 돌봄 리포트 자동 검증 결과 — 초안 → AI 영양사·AI 간호사 검증 → 자동 승인·발송 / 재작성 / 보류
   관리자용 탭과 보호자용 탭에 각각 해당 점수와 검증 내용을 보여 준다 */
export const VERIFY_DECISION = {
  pass: { label: '검증 통과 · 자동 승인', cls: 'bg-emerald-600 text-white', box: 'bg-emerald-50/70 ring-emerald-200' },
  pass_staff_only: { label: '관리자용만 자동 승인', cls: 'bg-blue-600 text-white', box: 'bg-blue-50/60 ring-blue-200' },
  hold: { label: '보류 · 담당자 검토', cls: 'bg-amber-500 text-white', box: 'bg-amber-50/70 ring-amber-200' },
}
const AG_VERDICT = { ok: '적합', fix: '보완 필요', contradiction: '모순', unsupported: '근거 없음', met: '충족', missing: '누락', conflict: '반대', support: '뒷받침', partial: '일부', unrelated: '무관' }
const PART_MAX = { '질환 지침 일치': 30, '우선순위 요인 대응': 25, '근거 인용 정확도': 20, '구체성': 15, '형식': 10, '관리자용과 내용 일치': 45, '읽기 쉬움': 30, '어조': 25 }

function ScoreBlock({ title, s, pass }) {
  if (!s) return null
  return (
    <div className="rounded-xl bg-white ring-1 ring-gray-200 p-3">
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-bold text-gray-800">{title}</p>
        <p className={`text-lg font-extrabold tabular-nums ${s.pass ? 'text-emerald-700' : 'text-amber-700'}`}>
          {Math.round(s.score)}<span className="text-[11px] font-normal text-gray-400"> / 100 · 통과 {pass}점</span>
        </p>
      </div>
      <div className="mt-2 space-y-1">
        {Object.entries(s.parts || {}).map(([k, v]) => {
          const max = PART_MAX[k] || 100
          return (
            <div key={k} className="flex items-center gap-2 text-[11px]">
              <span className="w-28 shrink-0 text-gray-600">{k}</span>
              <span className="flex-1 h-1.5 rounded-full bg-gray-100 overflow-hidden"><span className={`block h-full ${v / max >= 0.8 ? 'bg-emerald-500' : 'bg-amber-400'}`} style={{ width: `${Math.min(100, (100 * v) / max)}%` }} /></span>
              <span className="w-12 text-right tabular-nums text-gray-500">{v}/{max}</span>
            </div>
          )
        })}
      </div>
      {s.gates?.length > 0 && (
        <ul className="mt-2 space-y-0.5">
          {s.gates.map((g, i) => <li key={i} className="text-[11px] text-rose-700">⛔ {g.label}{g.detail?.length ? ` — ${g.detail.join(' / ')}` : ''}</li>)}
        </ul>
      )}
    </div>
  )
}

function AgentCard({ kind, info, issues }) {
  return (
    <div className="rounded-xl bg-white ring-1 ring-gray-200 p-3 flex gap-3">
      <span className="shrink-0 self-start rounded-lg bg-sky-50 ring-1 ring-sky-100 p-1"><PixelSprite kind={kind} scale={2} /></span>
      <div className="min-w-0 flex-1">
        <p className="text-xs font-bold text-gray-800">{info?.name || (kind === 'nurse' ? 'AI 간호사' : 'AI 영양사')}
          <span className="ml-1.5 font-normal text-[10px] text-gray-400">{info?.items?.join(' · ')}</span></p>
        {info?.comment && <p className="mt-1 text-[12px] text-gray-700 leading-5">“{info.comment}”</p>}
        {!info && <p className="mt-1 text-[11px] text-gray-400">검증 결과 없음 (이전 버전 또는 실행 실패)</p>}
        {issues.length > 0 ? (
          <ul className="mt-1.5 space-y-0.5">{issues.map((x, i) => <li key={i} className="text-[11px] text-amber-800">· {x}</li>)}</ul>
        ) : info && <p className="mt-1 text-[11px] text-emerald-700">지적 사항 없음</p>}
      </div>
    </div>
  )
}

export function VerifyPanel({ v, tab = 'staff' }) {
  if (!v) return null
  const d = VERIFY_DECISION[v.decision] || VERIFY_DECISION.hold
  const last = v.attempts?.[v.attempts.length - 1] || {}
  const ag = last.agent || {}
  const st = ag.staff || {}
  const say = (n, x) => `${n}: ${AG_VERDICT[x.verdict] || x.verdict || `${x.score}점`}${x.reason ? ` — ${x.reason}` : ''}`
  const bad = (x) => x && ((x.verdict && x.verdict !== 'ok') || (x.verdict == null && x.score != null && x.score < 2))
  const issuesOf = (k) => [
    ...(k === 'nurse' ? [['요약', st.summary], ['관찰', st.monitoring], ['주의사항', st.cautions]] : [['식사 지침', st.meal_guidance]]),
    ...(st.actions || []).filter((a) => a.agent === k).map((a) => [`조치 ${a.index}`, a]),
  ].filter(([, x]) => bad(x)).map(([n, x]) => say(n, x))
    .concat((st.disease_alignment || []).filter((x) => x.agent === k && x.verdict !== 'met').map((x) => say(x.condition, x)))
    .concat((st.citations || []).filter((c) => c.agent === k && c.verdict !== 'support').map((c) => say(`근거 [${c.tag}]`, c)))
  const gIssues = Object.entries(ag.guardian || {}).filter(([, x]) => bad(x))
    .map(([k, x]) => say({ consistency: '관리자용과 일치', readability: '읽기 쉬움', tone: '어조' }[k] || k, x))
  const send = v.send
  return (
    <div className={`mb-4 rounded-xl ring-1 p-4 ${d.box}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-xs font-bold rounded-full px-2.5 py-0.5 ${d.cls}`}>{d.label}</span>
        <span className="text-xs text-gray-700">{v.reason}</span>
        {v.rewrites > 0 && <span className="text-[11px] rounded-full bg-white px-2 py-0.5 ring-1 ring-gray-200 text-gray-600">재작성 {v.rewrites}회</span>}
        {last.verifier && <span className="text-[11px] text-gray-400">검증 {last.verifier}</span>}
        <span className="text-[10px] text-gray-400" title="서버 검증 버전 — 최신은 2026-11-24-v3">{v.version}</span>
      </div>
      {send && (
        <p className={`mt-1.5 text-[11px] ${send.ok ? 'text-emerald-800' : 'text-gray-600'}`}>
          {send.ok ? `보호자 ${send.results?.length || 0}명에게 자동 ${send.mode === 'dry_run' ? '테스트 발송(미리보기)' : '발송'}` : `자동 발송 안 함 — ${send.reason}`}
        </p>
      )}
      {v.edited_after && <p className="mt-1.5 text-[11px] text-amber-800">검증 이후 담당자가 내용을 고쳤습니다. 아래 점수는 수정 전 기준입니다.</p>}

      {tab === 'staff' ? (<>
        <div className="mt-3 grid md:grid-cols-2 gap-3">
          <ScoreBlock title="관리자용 점수" s={v.final?.staff} pass={v.thresholds?.staff} />
          <div className="space-y-2">
            <AgentCard kind="nutritionist" info={ag.agents?.nutritionist} issues={issuesOf('nutritionist')} />
            <AgentCard kind="nurse" info={ag.agents?.nurse} issues={issuesOf('nurse')} />
          </div>
        </div>
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold text-gray-700">항목별 검증 내용</summary>
          <div className="mt-2 grid md:grid-cols-2 gap-3 text-[11px]">
            <div>
              <p className="font-bold text-gray-700 mb-1">질환별 지침 점검</p>
              <ul className="space-y-0.5">
                {(last.rule?.must || []).map((m, i) => (
                  <li key={i} className={m.ok ? 'text-gray-600' : 'text-amber-800'}>{m.ok ? '✓' : '✗'} {m.condition} — {m.item} <span className="text-gray-400">({m.source})</span></li>
                ))}
                {!last.rule?.must?.length && <li className="text-gray-400">해당 조건 없음</li>}
              </ul>
              <p className="font-bold text-gray-700 mt-2 mb-1">돌봄 우선순위 요인 (모두 포함해야 통과)</p>
              <ul className="space-y-0.5">
                {(last.rule?.coverage || []).map((c, i) => <li key={i} className={c.ok ? 'text-gray-600' : 'text-rose-700'}>{c.ok ? '✓' : '✗'} {c.factor} ({c.rules.join('/')})</li>)}
                {!last.rule?.coverage?.length && <li className="text-gray-400">해당 요인 없음</li>}
              </ul>
            </div>
            <div>
              <p className="font-bold text-gray-700 mb-1">식사 해결 · 구체성 (식사 조치는 메뉴·양·시점 모두)</p>
              <ul className="space-y-0.5">
                {(last.rule?.spec_actions || []).map((x) => (
                  <li key={x.index} className={x.ok ? 'text-gray-600' : 'text-amber-800'}>
                    {x.ok ? '✓' : '✗'} 조치 {x.index} — {x.exempt ? '예외(의료진 확인·재평가)' : <>{x.meal === false ? '관찰 위주 · ' : '식사 · '}{Object.entries(x.has).map(([k, on]) => `${k}${on ? '○' : '×'}`).join(' ')}</>}
                  </li>
                ))}
              </ul>
              {last.rule?.format_issues?.length > 0 && <p className="mt-2 text-gray-600">형식: {last.rule.format_issues.join(' · ')}</p>}
            </div>
          </div>
          {v.attempts?.length > 1 && (
            <div className="mt-3">
              <p className="text-[11px] font-bold text-gray-700 mb-1">재작성 이력</p>
              <ol className="space-y-1.5">
                {v.attempts.map((t) => (
                  <li key={t.attempt} className="text-[11px] text-gray-600">
                    <span className="font-semibold">{t.attempt}차</span> 관리자용 {Math.round(t.scores?.staff?.score)} · 보호자용 {Math.round(t.scores?.guardian?.score)} → {({ rewrite: '재작성', pass: '통과', pass_staff_only: '관리자용만 통과', hold: '보류' })[t.decision]}
                    {t.decision === 'rewrite' && t.feedback_out?.length > 0 && (
                      <ul className="ml-4 list-disc pl-3 text-gray-500">{t.feedback_out.map((x, i) => <li key={i}>{x}</li>)}</ul>
                    )}
                  </li>
                ))}
              </ol>
            </div>
          )}
        </details>
      </>) : (
        <div className="mt-3 grid md:grid-cols-2 gap-3">
          <ScoreBlock title="보호자용 점수" s={v.final?.guardian} pass={v.thresholds?.guardian} />
          <AgentCard kind="nurse" info={ag.agents?.nurse && { ...ag.agents.nurse, items: ['보호자 안내문'], comment: '' }} issues={gIssues} />
        </div>
      )}
    </div>
  )
}

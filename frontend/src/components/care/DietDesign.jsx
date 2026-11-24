import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import api from '../../lib/api'
import { errMsg, fmtDate } from './CareUI'
import { CrewWalk } from './PixelCrew'

/* 맞춤 식단 설계 — 솔루션 > 맞춤 식단 설계
   ① 일반식 28일 식단(NSGA-II) → 영양사 검토·수정·승인
   ② 개인화: 죽식·백김치 + 질환 맞춤 대체찬(고령친화식품, 끼니당 2개) + 현장 단계 배식량
   ③ 재고·시설 선호도(잔반)·어르신 식단 설정 */

const PRESETS = [
  { key: 'quick', label: '빠르게', desc: '약 2~3분' },
  { key: 'standard', label: '표준', desc: '약 4~6분' },
  { key: 'thorough', label: '정밀', desc: '약 8~12분' },
]
const RUN_STATUS = {
  queued: { label: '대기', cls: 'bg-slate-100 text-slate-600' },
  running: { label: '계산 중', cls: 'bg-amber-50 text-amber-800' },
  done: { label: '검토 필요', cls: 'bg-navy-50 text-navy-700' },
  approved: { label: '승인됨', cls: 'bg-emerald-50 text-emerald-700' },
  failed: { label: '실패', cls: 'bg-rose-50 text-rose-700' },
  cancelled: { label: '중지됨', cls: 'bg-slate-100 text-slate-500' },
}
const SLOTS = ['밥', '국', '주찬', '부찬1', '부찬2', '김치']
const SLOT_CAT = { 밥: '밥', 국: '국', 주찬: '주찬', 부찬1: '부찬', 부찬2: '부찬', 김치: '김치' }
const MEALS = ['아침', '점심', '저녁']
const SUBTABS = [
  { key: 'menu', label: '28일 식단표' },
  { key: 'serving', label: '개인 배식표' },
  { key: 'purchase', label: '주간 발주' },
  { key: 'stock', label: '재고 리포트' },
  { key: 'subsum', label: '대체찬 요약' },
  { key: 'subs', label: '대체찬·죽' },
  { key: 'settings', label: '재고·선호도·설정' },
]
// 진행 문구 → 전체 진행률(0~1). 실측: 최적화 ≈ 절반, 개인별 배식량 ≈ 절반, 나머지는 몇 초
const TYPICAL_SEC = { quick: 90, standard: 130, thorough: 220, edit: 65 }   // 어르신 70명 기준
function progressOf(run) {
  const msg = String(run?.progress || '')
  const edit = !!run?.parent_run_id
  const [o0, o1] = edit ? [0, 0] : [0.03, 0.5]          // 최적화 구간
  const [s0, s1] = edit ? [0.1, 0.97] : [0.58, 0.97]     // 배식량 구간
  let m
  if ((m = msg.match(/(\d+)\/(\d+)세대/))) return o0 + (o1 - o0) * (+m[1] / +m[2])
  if ((m = msg.match(/(\d+)\/(\d+)끼/))) return s0 + (s1 - s0) * (+m[1] / +m[2])
  if (msg.includes('저장')) return 0.98
  if (msg.includes('발주')) return 0.975
  if (msg.includes('배식량')) return s0
  if (msg.includes('대체찬')) return s0 - 0.04
  if (msg.includes('식사형태')) return s0 - 0.07
  if (msg.includes('일반식 최적화')) return o0
  if (msg.includes('프로파일')) return 0.02
  return 0.01
}
function fmtSec(sec) {
  sec = Math.max(0, Math.round(sec))
  if (sec < 60) return `${sec}초`
  return `${Math.floor(sec / 60)}분${sec % 60 ? ` ${sec % 60}초` : ''}`
}
function useNow(on) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!on) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [on])
  return now
}
function estimate(run, now, nResidents) {
  const p = progressOf(run)
  const elapsed = Math.max(0, (now - new Date(run.created_at).getTime()) / 1000)
  const key = run.parent_run_id ? 'edit' : (run.params?.preset || 'standard')
  const typical = (TYPICAL_SEC[key] || 130) * Math.max(0.5, (nResidents || 70) / 70)
  // 초반엔 평소 소요 시간, 진행될수록 실제 속도 기준으로
  const byRate = p > 0.05 ? elapsed * (1 - p) / p : Infinity
  const w = Math.min(1, Math.max(0, (p - 0.05) / 0.3))
  const remain = w >= 1 ? byRate : Number.isFinite(byRate) ? w * byRate + (1 - w) * Math.max(0, typical - elapsed) : Math.max(0, typical - elapsed)
  return { p, elapsed, remain: Math.max(remain, p < 0.99 ? 5 : 0) }
}
const STAGES = [
  { key: '프로파일', label: '어르신 정보' },
  { key: '최적화', label: '일반식 28일 최적화' },
  { key: '식사형태', label: '죽·백김치' },
  { key: '대체찬', label: '대체찬' },
  { key: '배식량', label: '개인별 배식량' },
  { key: '저장', label: '발주·저장' },
]
// 식단 설계 중 AI 영양사 말풍선 — 지금 단계에 맞춰
const STAGE_LINES = [
  ['어르신 정보 읽는 중…', '질환·식사형태 확인 중', '못 드시는 재료 확인 중'],
  ['28일 식단 조합 짜는 중…', '영양 기준 맞추는 중', '반복 메뉴 줄이는 중', '한 끼 어울림 보는 중'],
  ['죽·백김치 준비 중…', '식사형태 맞추는 중'],
  ['어르신별 대체찬 고르는 중…', '못 드시는 재료 바꾸는 중'],
  ['개인별 배식량 계산 중…', '열량·단백질 맞추는 중'],
  ['발주량 정리 중…', '식단표 저장 중'],
]
function stageIdx(msg) {
  msg = String(msg || '')
  if (msg.includes('저장') || msg.includes('발주')) return 5
  if (msg.includes('배식량')) return 4
  if (msg.includes('대체찬')) return 3
  if (msg.includes('식사형태')) return 2
  if (msg.includes('최적화')) return 1
  return 0
}

function RunProgress({ run, nResidents, big, onStop }) {
  const [stopping, setStopping] = useState(false)
  const stop = async () => {
    if (!onStop) return
    setStopping(true)
    try { await onStop(run.id) } finally { setStopping(false) }
  }
  const now = useNow(true)
  const { p, elapsed, remain } = estimate(run, now, nResidents)
  const si = stageIdx(run.progress)
  const stages = run.parent_run_id ? STAGES.filter((s) => !['프로파일', '최적화'].includes(s.key)) : STAGES
  if (!big) {
    return (
      <div className="mt-1.5">
        <div className="h-1.5 rounded-full bg-amber-100 overflow-hidden">
          <div className="h-full bg-amber-500 transition-all duration-1000" style={{ width: `${Math.round(p * 100)}%` }} />
        </div>
        <p className="mt-1 text-[11px] text-muted tabular-nums">{Math.round(p * 100)}% · 약 {fmtSec(remain)} 남음</p>
      </div>
    )
  }
  return (
    <div className="surface p-8 md:p-10">
      <div className="flex items-center gap-3">
        <span className="inline-block h-5 w-5 rounded-full border-2 border-navy-200 border-t-navy-600 animate-spin" />
        <p className="text-base font-bold text-navy-900">{run.status === 'queued' ? '계산 대기 중' : run.parent_run_id ? '수정본 계산 중' : '식단 설계 계산 중'}</p>
        <p className="ml-auto text-sm tabular-nums text-navy-700">약 <b>{fmtSec(remain)}</b> 남음</p>
        {onStop && <button className="btn-secondary text-xs" disabled={stopping} onClick={stop}>{stopping ? '멈추는 중…' : '계산 멈추기'}</button>}
      </div>
      <div className="mt-4 h-2.5 rounded-full bg-navy-50 overflow-hidden">
        <div className="h-full rounded-full bg-navy-600 transition-all duration-1000" style={{ width: `${Math.max(2, Math.round(p * 100))}%` }} />
      </div>
      <div className="mt-2 flex text-xs text-muted tabular-nums">
        <span>{Math.round(p * 100)}%</span>
        <span className="ml-auto">경과 {fmtSec(elapsed)}</span>
      </div>
      <div className="mt-5">
        <CrewWalk crew={['nutritionist']} title={run.parent_run_id ? 'AI 영양사가 수정본을 다시 계산하고 있어요' : 'AI 영양사가 식단을 짜고 있어요'}
          lines={{ nutritionist: STAGE_LINES[si] }} />
      </div>
      <ol className="grid grid-cols-2 md:grid-cols-6 gap-2">
        {stages.map((s) => {
          const i = STAGES.indexOf(s)
          const st = i < si ? 'done' : i === si ? 'now' : 'todo'
          return (
            <li key={s.key} className={`rounded-xl px-3 py-2 text-xs ${st === 'done' ? 'bg-emerald-50 text-emerald-700' : st === 'now' ? 'bg-navy-900 text-white font-semibold' : 'bg-navy-50/60 text-muted'}`}>
              {st === 'done' ? '✓ ' : ''}{s.label}
            </li>
          )
        })}
      </ol>
      <p className="mt-4 text-xs text-muted">{run.progress}</p>
      <p className="mt-1 text-xs text-muted">이 화면을 닫거나 다른 메뉴로 가도 서버에서 계속 계산합니다. 다시 들어오면 진행 상황이 이어서 보입니다.
        멈추면 진행 중인 단계가 끝나는 대로(보통 몇 초~십여 초) 중지되고, 결과는 저장되지 않습니다.</p>
    </div>
  )
}

const dayNo = (d) => parseInt(String(d).replace(/\D/g, ''), 10) || 0
const pct = (a, b) => (b ? Math.round((100 * a) / b) : null)

function Stat({ label, value, unit, sub, tone }) {
  return (
    <div className={`rounded-2xl px-4 py-3 ${tone || 'bg-navy-50/70'}`}>
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 text-xl font-extrabold tabular-nums text-navy-900">
        {value ?? '–'}<span className="ml-0.5 text-xs font-normal text-muted">{unit}</span>
      </p>
      {sub && <p className="mt-0.5 text-[11px] text-muted">{sub}</p>}
    </div>
  )
}

function Section({ title, right, children, className = '', bare = false }) {
  if (bare) {                                    // 접힌 상자(Fold) 안에서는 제목·테두리 없이
    return (
      <div className={className}>
        {right && <div className="flex flex-wrap items-center justify-end gap-2 mb-3">{right}</div>}
        {children}
      </div>
    )
  }
  return (
    <section className={`surface p-5 ${className}`}>
      {(title || right) && (
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <h3 className="text-sm font-bold text-navy-900">{title}</h3>
          <div className="ml-auto flex flex-wrap items-center gap-2">{right}</div>
        </div>
      )}
      {children}
    </section>
  )
}

/* [2026-11-24] 접어 두는 상세 — 제목 한 줄 + 요약, 누르면 펼침 */
function Fold({ id, title, summary, children, defaultOpen = false }) {
  return (
    <details id={id} className="surface group" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-3.5 [&::-webkit-details-marker]:hidden">
        <span className="text-[10px] text-muted transition-transform group-open:rotate-90">▶</span>
        <span className="shrink-0 text-sm font-bold text-navy-900">{title}</span>
        {summary && <span className="min-w-0 truncate text-xs text-muted">{summary}</span>}
      </summary>
      <div className="px-5 pb-5">{children}</div>
    </details>
  )
}

function Table({ cols, rows, empty = '자료가 없습니다.', minW = 640, rowKey }) {
  if (!rows?.length) return <p className="text-sm text-muted py-4 text-center">{empty}</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" style={{ minWidth: minW }}>
        <thead>
          <tr className="text-left text-[11px] text-muted border-b border-navy-100">
            {cols.map((c) => <th key={c.key} className={`py-2 pr-3 whitespace-nowrap ${c.right ? 'text-right' : ''}`}>{c.label}</th>)}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={rowKey ? rowKey(r, i) : i} className="border-b border-navy-50 last:border-0 align-top">
              {cols.map((c) => (
                <td key={c.key} className={`py-1.5 pr-3 ${c.right ? 'text-right tabular-nums' : ''} ${c.cls || ''}`}>
                  {c.render ? c.render(r) : r[c.key] ?? '–'}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const OK = ({ v }) => <span className={v === '✅' ? 'text-emerald-600' : 'text-amber-600'}>{v === '✅' ? '충족' : '확인'}</span>

/* ─────────────────────────── 메인 ─────────────────────────── */

/* [2026-11-24] 시설 개선안 반영 — 시설 진단 > 개선안에서 넘어오면 켜진 상태로 시작 */
function FacilityPlanBox({ on, setOn, plan, err }) {
  return (
    <div className={`mt-4 rounded-2xl p-4 ring-1 ${on ? 'bg-emerald-50/60 ring-emerald-200' : 'bg-white ring-navy-100'}`}>
      <label className="flex items-center gap-2 text-sm font-bold text-navy-900">
        <input type="checkbox" checked={on} onChange={(e) => setOn(e.target.checked)} />
        시설 개선안 반영
        <span className="font-normal text-xs text-muted">시설 진단의 관리 우선순위를 공통 식단 최적화에 더합니다. 기존 기준(KDRI·개인 맞춤 기준·식단 규칙)은 그대로 지킵니다.</span>
      </label>
      {on && err && <p className="mt-2 text-xs text-rose-700">{err}</p>}
      {on && plan && (
        <div className="mt-3 grid md:grid-cols-2 gap-3">
          <div>
            <p className="text-xs font-bold text-emerald-800 mb-1.5">식단에 반영 ({plan.items.length}건)</p>
            {plan.items.length ? (
              <ul className="space-y-1.5">
                {plan.items.map((x) => (
                  <li key={x.id} className="text-xs leading-5 text-slate-700">
                    <span className="font-semibold text-navy-900">{x.title}</span>
                    <span className="ml-1 text-muted">{x.severity_label}</span>
                    <ul className="ml-3 list-disc pl-3 text-[11px] text-slate-600">{x.how.map((h) => <li key={h}>{h}</li>)}</ul>
                  </li>
                ))}
              </ul>
            ) : <p className="text-xs text-muted">식단으로 반영할 개선안이 없습니다.</p>}
          </div>
          <div>
            <p className="text-xs font-bold text-slate-600 mb-1.5">식단 외 조치 ({plan.outside.length}건) — 시설 진단 화면에서 운영으로 대응</p>
            <ul className="space-y-1">
              {plan.outside.map((x) => <li key={x.id} className="text-[11px] text-muted">· {x.title}</li>)}
            </ul>
            {plan.avoid_menus?.length > 0 && <p className="mt-2 text-[11px] text-slate-600">후보에서 제외할 잔반 많은 메뉴: {plan.avoid_menus.join(', ')}</p>}
          </div>
        </div>
      )}
    </div>
  )
}

/* 설계 결과에 개선안이 얼마나 반영됐는지 — 개선안 항목마다 '이 식단' vs '같은 후보에서 무작위로 고른 식단' */
const fmtEff = (v) => (v == null ? '–' : Number.isInteger(v) ? v.toLocaleString() : v.toLocaleString(undefined, { maximumFractionDigits: 1 }))
function EffectRow({ r }) {
  const tone = r.good == null ? 'text-muted' : r.good ? 'text-emerald-700' : 'text-slate-500'
  const arrow = r.diff == null || r.diff === 0 ? '' : r.diff > 0 ? '▲' : '▼'
  return (
    <tr className="border-b border-navy-50 last:border-0">
      <td className="py-1 pr-2 text-slate-700">{r.label}</td>
      <td className="py-1 pr-2 text-right tabular-nums font-semibold text-navy-900 whitespace-nowrap">{fmtEff(r.value)}<span className="ml-0.5 text-[10px] font-normal text-muted">{r.unit}</span></td>
      <td className="py-1 pr-2 text-right tabular-nums text-muted whitespace-nowrap">{r.base == null ? '–' : `${fmtEff(r.base)}${r.unit}`}</td>
      <td className={`py-1 text-right tabular-nums whitespace-nowrap ${tone}`}>
        {r.diff == null ? '' : <>{arrow} {fmtEff(Math.abs(r.diff))}{r.good ? ' ✓' : ''}</>}
      </td>
    </tr>
  )
}
function FacilityPlanResult({ fp, bare = false }) {
  if (!fp) return null
  const w = Object.entries(fp.weights || {}).map(([k, v]) => `${NUT_KO[k] || k} ×${v}`).join(' · ')
  // 같은 지표를 쓰는 개선안(예: 섭취율 관련 3건)은 한 카드로 묶는다
  const groups = []
  for (const e of fp.effects || []) {
    const key = JSON.stringify(e.rows)
    const g = groups.find((x) => x.key === key && e.rows.length)
    if (g) g.items.push(e)
    else groups.push({ key, items: [e], rows: e.rows, examples: e.examples, examplesLabel: e.examples_label })
  }
  const nGood = (fp.effects || []).filter((e) => e.rows.some((r) => r.good)).length
  return (
    <div className={bare ? '' : 'surface p-5 ring-1 ring-emerald-200'}>
      <div className="flex flex-wrap items-center gap-2">
        {!bare && <p className="text-sm font-extrabold text-navy-900">시설 개선안이 식단에 어떻게 반영됐나</p>}
        <span className="badge bg-emerald-50 text-emerald-700">{fp.items?.length || 0}건 반영</span>
        {fp.effects && <span className="badge bg-navy-50 text-navy-700">비교 기준보다 나아진 항목 {nGood}/{fp.effects.length}</span>}
      </div>
      <p className="mt-1 text-xs text-muted">
        각 개선안을 식단 최적화의 무게·선호·제한으로 바꿔 설계했습니다{w && ` (영양 위반 가중치 ${w})`}.
        {' '}비교 기준은 {fp.baseline || '같은 후보 메뉴에서 무작위로 고른 식단'}입니다 — 기준(KDRI·개인 맞춤·식단 규칙)은 그대로 지킵니다.
      </p>
      {!fp.effects ? (
        <p className="mt-3 text-xs text-muted">이 설계는 이전 버전에서 만들어져 항목별 반영 결과가 없습니다. 다시 최적화하면 항목별로 보입니다.</p>
      ) : (
        <div className="mt-3 grid lg:grid-cols-2 gap-3">
          {groups.map((g) => (
            <div key={g.items[0].id} className="rounded-xl bg-white ring-1 ring-navy-100 p-3">
              {g.items.map((x) => (
                <p key={x.id} className="text-[13px] font-bold text-navy-900 leading-5">
                  {x.title} <span className="text-[11px] font-normal text-muted">{x.severity_label}</span>
                </p>
              ))}
              <ul className="mt-1 mb-2 text-[11px] text-slate-500 list-disc pl-4">
                {g.items[0].how?.map((h) => <li key={h}>{h}</li>)}
              </ul>
              {g.rows.length > 0 && (
                <table className="w-full text-xs">
                  <thead><tr className="text-[10px] text-muted border-b border-navy-100">
                    <th className="py-1 text-left font-normal">지표</th><th className="py-1 text-right font-normal">이 식단</th>
                    <th className="py-1 text-right font-normal">비교 기준</th><th className="py-1 text-right font-normal">차이</th>
                  </tr></thead>
                  <tbody>{g.rows.map((r) => <EffectRow key={r.label} r={r} />)}</tbody>
                </table>
              )}
              {g.examples?.length > 0 && (
                <div className="mt-2 flex flex-wrap items-center gap-1">
                  <span className="text-[10px] text-muted mr-1">{g.examplesLabel || '식단에 들어간 메뉴'}</span>
                  {g.examples.map(([n, k]) => (
                    <span key={n} className={`rounded-full px-2 py-0.5 text-[11px] ${g.examplesLabel ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-800'}`}>{n}{k > 1 ? ` ×${k}` : ''}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <p className="mt-3 text-[11px] text-muted">
        식단표에서 <span className="text-emerald-600">●</span> 개선안으로 더 고른 메뉴, <span className="text-rose-500">●</span> 개선안이 줄이려는 메뉴(제한)가 들어갔고 그 끼니 나트륨이 600 mg을 넘은 경우입니다. 점에 마우스를 올리면 어떤 개선안 때문인지 보입니다.
        {' '}▲▼는 비교 기준과의 차이이고, ✓는 개선안이 원하는 방향입니다.
      </p>
      {fp.outside?.length > 0 && <p className="mt-1 text-[11px] text-muted">식단 외 조치(운영): {fp.outside.map((x) => x.title).join(' · ')}</p>}
    </div>
  )
}
const NUT_KO = { sodium: '나트륨', energy: '열량', protein: '단백질', fiber: '식이섬유', potassium: '칼륨' }

export default function DietDesign({ facilityPlan = false }) {
  const [usePlan, setUsePlan] = useState(!!facilityPlan)
  const [plan, setPlan] = useState(null)
  const [planErr, setPlanErr] = useState('')
  const [status, setStatus] = useState(null)
  const [runId, setRunId] = useState(null)
  const [run, setRun] = useState(null)
  const [sub, setSub] = useState('menu')
  const [preset, setPreset] = useState('standard')
  const [useAi, setUseAi] = useState(true)          // AI 영양사가 파레토 후보 중 선택
  const [useReview, setUseReview] = useState(true)  // AI 식단 검토 (어색한 칸 교체 제안 → 코드 검증 후 반영)
  const [useRefine, setUseRefine] = useState(true)  // Stage 2 AI 임상 영양사 어르신별 종합 판단
  const [useAgentAi, setUseAgentAi] = useState(false)  // Stage 1 AI 영역 전문가 (근거 검색 RAG + 판단·인용)
  const [aiStatus, setAiStatus] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  const loadStatus = () => api.get('/care/diet/status').then((r) => {
    setStatus(r.data)
    setRunId((cur) => cur || r.data.runs?.find((x) => ['done', 'approved'].includes(x.status))?.id || r.data.runs?.[0]?.id || null)
    return r.data
  }).catch((e) => setErr(errMsg(e)))

  const loadRun = (id) => id && api.get(`/care/diet/runs/${id}`, { timeout: 60000 }).then((r) => setRun(r.data)).catch((e) => setErr(errMsg(e)))

  useEffect(() => {
    loadStatus()
    api.get('/care/diet/llm-status').then((r) => setAiStatus(r.data)).catch(() => setAiStatus(null))
  }, [])
  useEffect(() => { setRun(null); loadRun(runId) }, [runId])
  useEffect(() => {
    if (!usePlan || plan) return
    api.get('/care/diet/facility-plan', { timeout: 60000 }).then((r) => { setPlan(r.data); setPlanErr('') })
      .catch((e) => setPlanErr(errMsg(e)))
  }, [usePlan])

  // 실행 중이면 4초마다 진행 상황 갱신
  const active = status?.runs?.find((x) => ['queued', 'running'].includes(x.status))
  useEffect(() => {
    clearTimeout(timer.current)
    if (active) {
      timer.current = setTimeout(async () => {
        const s = await loadStatus()
        const still = s?.runs?.find((x) => x.id === active.id)
        if (still && ['done', 'failed', 'cancelled'].includes(still.status)) { setRunId(still.id); loadRun(still.id) }
      }, 4000)
    }
    return () => clearTimeout(timer.current)
  }, [status])

  const start = async () => {
    setErr(''); setBusy(true)
    try {
      const r = await api.post('/care/diet/runs', { preset, selector: useAi ? 'llm' : 'rule', reviewer: useReview ? 'llm' : 'off', refiner: useRefine ? 'llm' : 'off', agent_mode: useAgentAi ? 'llm' : 'rule', facility_plan: usePlan }, { timeout: 60000 })
      setRunId(r.data.id)
      await loadStatus()
    } catch (e) { setErr(errMsg(e)) } finally { setBusy(false) }
  }

  const stopRun = async (id) => {
    setErr('')
    try { await api.post(`/care/diet/runs/${id}/cancel`); await loadStatus() } catch (e) { setErr(errMsg(e)) }
  }

  const approve = async (startDate) => {
    setErr('')
    try { await api.post(`/care/diet/runs/${runId}/approve`, { start_date: startDate || null }); await loadStatus(); loadRun(runId) } catch (e) { setErr(errMsg(e)) }
  }

  const ready = status?.residents_ready ?? 0
  const live = run && { ...run, ...(status?.runs?.find((x) => x.id === run.id) || {}) }

  return (
    <div className="space-y-4">
      {err && <p className="text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}

      <Section title="식단 설계 실행"
        right={<>
          <div className="flex rounded-xl bg-navy-50 p-1">
            {PRESETS.map((p) => (
              <button key={p.key} onClick={() => setPreset(p.key)} title={p.desc}
                className={`px-3 py-1 rounded-lg text-xs font-semibold ${preset === p.key ? 'bg-white text-navy-900 shadow-sm' : 'text-muted'}`}>{p.label}</button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-navy-700"
            title={aiStatus?.ready ? `최적화가 찾은 식단 후보 중 AI 영양사(${aiStatus.model})가 시설 상황을 보고 고릅니다` : 'AI 키가 설정되지 않아 규칙(균형점)으로 고르고, 후보 비교표만 보여 줍니다'}>
            <input type="checkbox" checked={useAi} onChange={(e) => setUseAi(e.target.checked)} />
            AI 영양사 선택{aiStatus && !aiStatus.ready && <span className="font-normal text-muted">(미설정)</span>}
          </label>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-navy-700"
            title="AI 영양사가 28일 식단을 읽고 어색한 조합·조리 부담·계절에 안 맞는 칸을 후보 메뉴로 바꾸자고 제안합니다. 영양·반복·조화 점수가 나빠지지 않는 제안만 반영됩니다.">
            <input type="checkbox" checked={useReview} onChange={(e) => setUseReview(e.target.checked)} />
            AI 식단 검토
          </label>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-navy-700"
            title="7개 영역마다 AI 영역 전문가가 그 영역 임상 지침(당뇨·고혈압·ESPEN·KDRI·IDDSI·식약처 약물 정보)에서 근거 문단을 찾아 판단 근거를 인용하고, 문제 점수를 규칙 값 ±0.2 안에서 다듬습니다. 안전성 문제 점수와 영양 기준 숫자는 바꾸지 않습니다. 어르신 수만큼 AI를 여러 번 부르므로 시간이 더 걸립니다.">
            <input type="checkbox" checked={useAgentAi} onChange={(e) => setUseAgentAi(e.target.checked)} />
            AI 영역 전문가(근거 검색)
          </label>
          <label className="flex items-center gap-1.5 text-xs font-semibold text-navy-700"
            title="7개 영역 평가를 AI 임상 영양사가 어르신별로 함께 보고, 영역 간 충돌 조정 · 허용 범위 안 기준 조정 · 문제 우선순위 재평가를 합니다 (NutriOrion Stage 2). 우선순위는 대체찬 배분에 쓰입니다.">
            <input type="checkbox" checked={useRefine} onChange={(e) => setUseRefine(e.target.checked)} />
            AI 개인 종합 판단
          </label>
          {active
            ? <button className="btn-secondary" onClick={() => stopRun(active.id)}>계산 멈추기</button>
            : <button className="btn-primary" disabled={busy || !ready} onClick={start}>식단 설계 실행</button>}
        </>}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="설계 대상 어르신" value={ready} unit={`/ ${status?.residents_total ?? '–'}명`} sub="진단 평가가 있는 어르신" />
          <Stat label="재고" value={status?.inventory?.count ?? 0} unit="품목"
            sub={status?.inventory?.updated_at ? `${fmtDate(status.inventory.updated_at)} 갱신` : '입력하면 일반식에서 먼저 사용'} />
          <Stat label="시설 선호도" value={status?.preference ? (status.preference.facility_mean * 100).toFixed(0) : '–'} unit={status?.preference ? '% 평균 섭취' : ''}
            sub={status?.preference ? `${status.preference.n_menus_observed}개 메뉴 · ${fmtDate(status.preference.updated_at)}` : '잔반 기록으로 계산 전'} />
          {active ? (
            <div className="rounded-2xl px-4 py-3 bg-amber-50">
              <p className="text-[11px] text-muted">진행 상태</p>
              <p className="mt-1 text-xl font-extrabold text-navy-900">{RUN_STATUS[active.status]?.label}</p>
              <RunProgress run={active} nResidents={ready} />
            </div>
          ) : (
            <Stat label="진행 상태" value={live ? RUN_STATUS[live.status]?.label : '–'} sub={live && fmtDate(live.created_at)} />
          )}
        </div>
        <FacilityPlanBox on={usePlan} setOn={setUsePlan} plan={plan} err={planErr} />
        {!ready && <p className="mt-3 text-xs text-muted">진단 화면에서 어르신 평가를 먼저 실행해야 식단을 설계할 수 있습니다.</p>}
        {status?.runs?.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {status.runs.map((x) => (
              <button key={x.id} onClick={() => setRunId(x.id)}
                className={`rounded-xl px-3 py-1.5 text-xs text-left ring-1 ${runId === x.id ? 'ring-navy-500 bg-navy-50' : 'ring-navy-100 bg-white hover:ring-navy-300'}`}>
                <span className="font-semibold text-navy-900">{fmtDate(x.created_at)} {new Date(x.created_at).toTimeString().slice(0, 5)}</span>
                <span className={`badge ml-1.5 ${RUN_STATUS[x.status]?.cls}`}>{RUN_STATUS[x.status]?.label}</span>
                {x.parent_run_id && <span className="ml-1 text-muted">{x.params?.candidate ? `후보 ${x.params.candidate}` : '수정본'}</span>}
                {!x.parent_run_id && x.params?.selector === 'llm' && <span className="ml-1 text-violet-600">AI</span>}
                {x.params?.facility_plan && <span className="ml-1 text-emerald-700" title={`시설 개선안 ${x.params.facility_plan.length}건 반영`}>개선안</span>}
                {x.status === 'failed' && x.error && <span className="ml-1 text-rose-600" title={x.error}>ⓘ</span>}
                {x.params?.preset && !x.parent_run_id && <span className="ml-1 text-muted">{PRESETS.find((p) => p.key === x.params.preset)?.label}</span>}
              </button>
            ))}
          </div>
        )}
      </Section>

      <div className="flex flex-wrap gap-2">
        {SUBTABS.map((t) => (
          <button key={t.key} onClick={() => setSub(t.key)}
            className={`px-4 py-2 rounded-full text-sm font-semibold ${sub === t.key ? 'bg-navy-600 text-white' : 'bg-white border border-navy-100 text-navy-700'}`}>{t.label}</button>
        ))}
      </div>

      {sub === 'settings' ? (
        <SettingsTab onChanged={loadStatus} />
      ) : sub === 'stock' ? (
        <StockTab />
      ) : !live ? (
        <div className="surface p-12 text-center text-muted">{runId ? '불러오는 중…' : '아직 설계 결과가 없습니다. 위에서 식단 설계를 실행하세요.'}</div>
      ) : live.status === 'failed' ? (
        <div className="surface p-6 text-sm text-rose-700">
          <p className="font-semibold">설계에 실패했습니다.</p>
          <p className="mt-1 break-all text-xs">{live.error || '원인을 알 수 없습니다. 다시 실행해 보세요.'}</p>
        </div>
      ) : live.status === 'cancelled' ? (
        <div className="surface p-10 text-center text-sm text-muted">계산을 중지한 설계입니다. 위에서 다시 실행하거나 다른 설계를 선택하세요.</div>
      ) : ['queued', 'running'].includes(live.status) || !live.menu ? (
        <RunProgress run={live} nResidents={ready} big onStop={stopRun} />
      ) : sub === 'menu' ? (
        <MenuTab run={live} onApprove={approve}
          onEdited={async (id) => { setRunId(id); await loadStatus() }} onRerun={start} setErr={setErr} />
      ) : sub === 'serving' ? (
        <ServingTab run={live} />
      ) : sub === 'purchase' ? (
        <PurchaseTab run={live} />
      ) : sub === 'subsum' ? (
        <SubsSummaryTab run={live} />
      ) : (
        <SubsTab run={live} />
      )}
    </div>
  )
}

/* ─────────────────────────── AI 영양사 선택 (파레토 후보 비교) ─────────────────────────── */

const SEL_COLS = [
  ['f1b', '기본 기준 f1 ↓', (s) => s.f1_기본기준],
  ['f1', '영양 위반 f1 ↓', (s) => s.목적함수?.['f1_영양']],
  ['f3', '반복·편중 f3 ↓', (s) => s.목적함수?.['f3_다양성']],
  ['f4', '조화 문제 f4 ↓', (s) => s.목적함수?.['f4_조화']],
  ['na', '나트륨 mg/일 ↓', (s) => s.하루평균_영양?.나트륨?.하루평균],
  ['su', '당류 g/일 ↓', (s) => s.하루평균_영양?.당류?.하루평균],
  ['pr', '단백질 g/일 ↑', (s) => s.하루평균_영양?.단백질?.하루평균],
  ['rp', '14일 반복 ↓', (s) => s.반복?.['반복_14일안']],
  ['hm', '한 끼 조화 ↑', (s) => s.조화?.한끼_평균],
  ['lo', '조화 낮은 끼니 ↓', (s) => s.조화?.낮은_끼니],
  ['tx', '다진찬 부적합 ↓', (s) => s.다진찬_부적합_끼니],
]
const HIGHER_BETTER = new Set(['pr', 'hm'])

function SelectionPanel({ run, onEdited, setErr, bare = false }) {
  const [busy, setBusy] = useState('')
  const sel = run.metrics?.selection
  const p = run.params || {}
  if (run.parent_run_id && p.candidate) {
    return (
      <div className={`${bare ? '' : 'surface px-5 py-3 '}text-sm text-navy-800`}>
        영양사가 <b>후보 {p.candidate}</b>를 골라 다시 계산한 식단입니다.
        {p.ai_choice && <span className="text-muted"> (AI 영양사 선택 {p.ai_choice} · 규칙 선택 {p.rule_choice || 'A'})</span>}
      </div>
    )
  }
  if (!sel?.candidates?.length) return null
  const cands = sel.candidates
  const chosen = sel.mode === 'llm' ? sel.choice : 'A'
  const best = Object.fromEntries(SEL_COLS.map(([k, , g]) => {
    const vals = cands.map((c) => g(c.summary)).filter((v) => v != null)
    return [k, HIGHER_BETTER.has(k) ? Math.max(...vals) : Math.min(...vals)]
  }))
  const useCand = async (id) => {
    setBusy(id); setErr('')
    try { const r = await api.post(`/care/diet/runs/${run.id}/candidate`, { candidate: id }); onEdited(r.data.id) }
    catch (e) { setErr(errMsg(e)) } finally { setBusy('') }
  }
  return (
    <Section title="AI 영양사 선택" bare={bare}
      right={sel.mode === 'llm'
        ? <span className="badge bg-violet-50 text-violet-700">후보 {sel.choice} 선택 · {sel.agreed_with_rule ? '규칙 선택과 같음' : `규칙 선택(A)과 다름`}</span>
        : <span className="badge bg-amber-50 text-amber-700">규칙 선택(A) 사용</span>}>
      {sel.mode === 'llm' ? (
        <div className="space-y-2 text-sm">
          {sel.summary && <p className="text-navy-900">{sel.summary}</p>}
          <div className="grid md:grid-cols-3 gap-3">
            <div className="rounded-xl bg-navy-50/60 px-3 py-2">
              <p className="text-[11px] font-bold text-muted mb-1">고른 이유</p>
              <ul className="list-disc pl-4 space-y-0.5 text-xs">{(sel.reasons || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
            <div className="rounded-xl bg-navy-50/60 px-3 py-2">
              <p className="text-[11px] font-bold text-muted mb-1">포기한 점</p>
              <p className="text-xs">{sel.tradeoffs || '–'}</p>
            </div>
            <div className="rounded-xl bg-amber-50 px-3 py-2">
              <p className="text-[11px] font-bold text-amber-800 mb-1">승인 전 확인할 점</p>
              <ul className="list-disc pl-4 space-y-0.5 text-xs">{(sel.check_before_approval || []).map((x, i) => <li key={i}>{x}</li>)}</ul>
            </div>
          </div>
          <p className="text-[11px] text-muted">AI 순위 {(sel.ranking || []).join(' > ')} · {sel.model} · {sel.latency_sec}초 · 프롬프트 {sel.prompt_version}</p>
          {sel.warnings?.some((w) => w.startsWith('입력에 없는 숫자')) && (
            <p className="text-[11px] text-amber-700">⚠ AI 설명에 입력에 없는 숫자가 있습니다 — 숫자는 아래 비교표로 확인하세요. ({sel.warnings.join(' · ')})</p>
          )}
        </div>
      ) : (
        <p className="text-xs text-muted">{sel.fallback || '규칙(균형점)으로 골랐습니다.'} 아래 후보를 비교해 다른 식단을 직접 고를 수 있습니다.</p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs tabular-nums">
          <thead>
            <tr className="text-muted border-b border-navy-100">
              <th className="text-left py-1.5 pr-2">후보</th>
              <th className="text-left py-1.5 pr-2">특징</th>
              {SEL_COLS.map(([k, label]) => <th key={k} className="text-right py-1.5 px-1.5 whitespace-nowrap">{label}</th>)}
              <th />
            </tr>
          </thead>
          <tbody>
            {cands.map((c) => (
              <tr key={c.id} className={`border-b border-navy-50 ${c.id === chosen ? 'bg-violet-50/60' : ''}`}>
                <td className="py-1.5 pr-2 font-bold text-navy-900 whitespace-nowrap">{c.id}{c.id === chosen && ' ✓'}</td>
                <td className="py-1.5 pr-2 text-muted whitespace-nowrap">{(c.tags || []).join(' · ')}</td>
                {SEL_COLS.map(([k, , g]) => {
                  const v = g(c.summary)
                  return <td key={k} className={`text-right py-1.5 px-1.5 ${v != null && v === best[k] ? 'font-bold text-emerald-700' : ''}`}>{v ?? '–'}</td>
                })}
                <td className="py-1.5 pl-2 text-right">
                  {c.id !== chosen && run.status !== 'approved' && (
                    <button className="btn-ghost !px-2 !py-0.5 text-[11px]" disabled={!!busy} onClick={() => useCand(c.id)}>
                      {busy === c.id ? '계산 중…' : '이 후보로'}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-1 text-[11px] text-muted">{!sel.f1_gate
          ? '모든 후보는 영양 기준(f1 ≤ 0.3)을 통과한 파레토 식단입니다.'
          : sel.f1_gate.n_pass > 0
            ? `기본 영양 기준(f1 ≤ ${sel.f1_gate.pass_f1}, 시설 개선안 제외)을 통과한 파레토 식단은 ${sel.f1_gate.n_pass}개(전체 ${sel.f1_gate.n_front}개)입니다${sel.f1_gate.n_pass < 3 ? ' — 통과 식단이 적어 영양 위반이 가장 적은 식단을 함께 보여 줍니다' : ''}. '기본 기준 f1'이 통과 여부이고, '영양 위반 f1'은 개선안 가중치를 넣은 최적화 점수입니다.`
            : `기본 영양 기준(f1 ≤ ${sel.f1_gate.pass_f1})을 통과한 후보가 없어, 영양 위반이 가장 적은 후보들 중에서 골랐습니다 (파레토 식단 ${sel.f1_gate.n_front}개).`}
          {' '}↓ 낮을수록 좋음 · ↑ 높을수록 좋음 · 굵은 초록 = 그 항목에서 가장 좋은 후보. '이 후보로'를 누르면 그 식단으로 대체찬·배식량을 다시 계산한 수정본이 만들어집니다.</p>
      </div>
    </Section>
  )
}

/* ─────────────────────────── AI 식단 검토 (교체 제안 → 코드 검증) ─────────────────────────── */

function ReviewPanel({ run, onEdited, setErr, bare = false }) {
  const [busy, setBusy] = useState('')
  const rv = run.metrics?.review
  if (!rv) return null
  if (rv.mode !== 'llm') {
    return <div className={`${bare ? '' : 'surface px-5 py-3 '}text-xs text-muted`}>AI 식단 검토: {rv.note || '검토하지 않았습니다.'}</div>
  }
  const acc = rv.accepted || [], rej = rv.rejected || []
  const revert = async (a) => {
    const key = `${a.day}|${a.meal}|${a.slot}`
    setBusy(key); setErr('')
    try {
      const r = await api.put(`/care/diet/runs/${run.id}/menu`, { changes: [{ 일차: `${a.day}일`, 끼니: a.meal, 칸: a.slot, 메뉴: a.current }] })
      onEdited(r.data.id)
    } catch (e) { setErr(errMsg(e)) } finally { setBusy('') }
  }
  const fd = (k) => (rv.f_after?.[k] != null && rv.f_before?.[k] != null ? (rv.f_after[k] - rv.f_before[k]).toFixed(3) : '–')
  return (
    <Section title="AI 식단 검토" bare={bare}
      right={<span className="badge bg-violet-50 text-violet-700">제안 {rv.n_suggested}건 · 반영 {acc.length} · 거절 {rej.length}</span>}>
      {rv.overall && <p className="text-sm text-navy-900">{rv.overall}</p>}
      {acc.length > 0 ? (
        <div className="mt-3 space-y-1.5">
          <p className="text-[11px] font-bold text-muted">반영한 교체 (식단표에 보라색으로 표시)</p>
          {acc.map((a) => (
            <div key={`${a.day}${a.meal}${a.slot}`} className="flex flex-wrap items-start gap-x-3 gap-y-1 rounded-xl bg-violet-50/60 px-3 py-2 text-xs">
              <span className="font-semibold text-navy-900 whitespace-nowrap">{a.day}일 {a.meal} {a.slot}</span>
              <span className="whitespace-nowrap"><span className="text-muted line-through">{a.current}</span> → <b className="text-violet-800">{a.replace_with}</b></span>
              {a.type && <span className="badge bg-white text-violet-700">{a.type}</span>}
              <span className="min-w-0 flex-1 text-navy-800">
                {a.problem}{a.why ? ` · ${a.why}` : ''}
                {a.calcium && (a.calcium[0] >= 100 || a.calcium[1] >= 100) && <span className="ml-1 text-muted">(칼슘 {a.calcium[0]}→{a.calcium[1]}mg)</span>}
                {a.code_note && <span className="block text-[11px] text-emerald-700">↳ {a.code_note}</span>}
              </span>
              {run.status !== 'approved' && (
                <button className="btn-ghost !px-2 !py-0.5 text-[11px]" disabled={!!busy} onClick={() => revert(a)}>
                  {busy === `${a.day}|${a.meal}|${a.slot}` ? '계산 중…' : '되돌리기'}
                </button>
              )}
            </div>
          ))}
        </div>
      ) : <p className="mt-2 text-xs text-muted">반영한 교체가 없습니다.</p>}
      {rej.length > 0 && (
        <details className="mt-3 text-xs">
          <summary className="cursor-pointer text-navy-700 font-semibold">반영하지 않은 제안 {rej.length}건 (코드 검증에서 거절)</summary>
          <div className="mt-2 space-y-1">
            {rej.map((r, i) => (
              <p key={i} className="text-muted">
                {r.day}일 {r.meal} {r.slot}: {r.current} → {r.replace_with} — <span className="text-amber-700">{r.reason}</span>
                {r.problem ? ` (제안 이유: ${r.problem})` : ''}
              </p>
            ))}
          </div>
        </details>
      )}
      <p className="mt-2 text-[11px] text-muted">
        검토 전후 점수 변화 f1 {fd('f1')} · f3 {fd('f3')} · f4 {fd('f4')} (음수 = 좋아짐) · {rv.model} · {rv.latency_sec}초 · 프롬프트 {rv.prompt_version}.
        제안은 후보 메뉴 안에서만, 앞뒤 3일 반복이 없고 영양·다양성·조화 점수가 0.01 넘게(검토 전체로도 0.01 넘게) 나빠지지 않을 때만 반영됩니다.
        칼슘·단백질 급원 반찬은 같은 급원 메뉴 중 점수가 가장 좋은 것으로만 바뀝니다.
      </p>
    </Section>
  )
}

/* ─────────────────────────── ① 식단표 ─────────────────────────── */

function MenuTab({ run, onApprove, onEdited, onRerun, setErr }) {
  const [askStart, setAskStart] = useState(false)
  const [startDate, setStartDate] = useState(run.start_date || run.params?.start_date || (() => {
    const d = new Date(Date.now() + 9 * 3600e3); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10)
  })())
  const [week, setWeek] = useState(1)
  const [detail, setDetail] = useState(false)     // 식단표에 영양 수치 열 보이기
  const [edits, setEdits] = useState({})          // "일차|끼니|칸" → 메뉴
  const [editing, setEditing] = useState(null)     // {일차, 끼니, 칸}
  const [options, setOptions] = useState(null)
  const [saving, setSaving] = useState(false)
  const m = run.metrics || {}
  const sel = m.selected || {}
  const res = run.result || {}
  const ss = res.serving_summary || {}

  const openEdit = (cell) => {
    setEditing(cell)
    if (!options) api.get('/care/diet/menu-options').then((r) => setOptions(r.data)).catch((e) => setErr(errMsg(e)))
  }
  const rows = (run.menu || []).filter((r) => Math.ceil(dayNo(r.일차) / 7) === week)
  const reviewed = useMemo(() => Object.fromEntries((m.review?.accepted || []).map((a) => [`${a.day}일|${a.meal}|${a.slot}`, a])), [run.id])
  const nEdits = Object.keys(edits).length
  const planTags = m.facility_plan?.menu_tags || {}

  const saveEdits = async () => {
    setSaving(true); setErr('')
    try {
      const changes = Object.entries(edits).map(([k, v]) => { const [일차, 끼니, 칸] = k.split('|'); return { 일차, 끼니, 칸, 메뉴: v } })
      const r = await api.put(`/care/diet/runs/${run.id}/menu`, { changes })
      setEdits({}); onEdited(r.data.id)
    } catch (e) { setErr(errMsg(e)) } finally { setSaving(false) }
  }

  // [2026-11-24] 화면 정리 — 식단표를 먼저, 점수·AI 판단·개선안은 한 줄 요약 + 접어 둔 상세
  const f1 = sel['f1_영양'] ?? sel['f1_영양위반']
  const okPct = pct(ss.끼니 - ss.조정불가, ss.끼니)
  const fp = m.facility_plan
  const fpGood = fp?.effects ? fp.effects.filter((e) => e.rows.some((r) => r.good)).length : null
  const selInfo = m.selection
  const rv = m.review
  const openFold = (id) => {
    const el = document.getElementById(id)
    if (el) { el.open = true; el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
  }
  const flags = (r) => {
    const out = []
    if (r['나트륨(mg)'] > 600) out.push({ t: '나트륨↑', c: 'bg-rose-50 text-rose-700', tip: `나트륨 ${r['나트륨(mg)']}mg (끼니 600mg 초과)` })
    if (r.조화 != null && r.조화 < 0.4) out.push({ t: '조화↓', c: 'bg-amber-50 text-amber-800', tip: `한 끼 조화 ${r.조화.toFixed(2)} (0.4 미만)` })
    if (r.다진찬주의 && r.다진찬주의 !== '-' && r.다진찬주의.includes('부적합')) out.push({ t: '다진찬', c: 'bg-slate-100 text-slate-700', tip: `다진찬 주의: ${r.다진찬주의}` })
    return out
  }

  return (
    <div className="space-y-4">
      {/* ① 한눈에 보기 + 승인 */}
      <section className="surface p-5">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-extrabold text-navy-900">28일 식단</h3>
          {run.parent_run_id && <span className="badge bg-amber-50 text-amber-800">영양사 수정본</span>}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {run.status === 'approved'
              ? <span className="badge bg-emerald-50 text-emerald-700">승인됨 · {fmtDate(run.approved_at)}{run.start_date ? ` · ${run.start_date} 시작` : ''}</span>
              : askStart ? (
                <span className="flex items-center gap-2 rounded-xl bg-navy-50 px-2 py-1">
                  <span className="text-xs text-navy-700">식단 1일차</span>
                  <input type="date" className="form-input !py-1 !w-auto" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                  <button className="btn-primary text-xs" disabled={!startDate} onClick={() => { setAskStart(false); onApprove(startDate) }}>승인 확정</button>
                  <button className="btn-ghost text-xs" onClick={() => setAskStart(false)}>취소</button>
                </span>
              ) : <button className="btn-primary" onClick={() => setAskStart(true)} disabled={nEdits > 0}>영양사 승인</button>}
            <button className="btn-secondary" onClick={onRerun}>다시 최적화</button>
          </div>
        </div>
        {askStart && <p className="mt-1 text-right text-[11px] text-muted">승인하면 주간 발주량이 입고로 재고에 기록됩니다</p>}
        <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="개인 배식 기준 충족" value={okPct} unit="%" tone={okPct >= 90 ? 'bg-emerald-50' : 'bg-amber-50'}
            sub={`나트륨 ${pct(ss.나트륨OK, ss.끼니) ?? '–'}% · 열량 ${pct(ss.열량OK, ss.끼니) ?? '–'}% · 단백질 ${pct(ss.단백질OK, ss.끼니) ?? '–'}%`} />
          <Stat label="영양 점수 (f1, 낮을수록 좋음)" value={f1} tone={f1 <= 0.3 ? 'bg-emerald-50' : 'bg-amber-50'} sub={f1 <= 0.3 ? '목표(0.3 이하) 충족' : '목표 0.3 이하 — 확인 필요'} />
          <Stat label="대체찬" value={res.substitutions?.length ?? 0} unit="건" sub={`${(res.residents || []).filter((x) => x.substitutions > 0).length}명 / ${res.residents?.length ?? '–'}명`} />
          {fp ? <Stat label="시설 개선안" value={fp.items?.length ?? 0} unit="건 반영" sub={fpGood != null ? `비교 기준보다 나아진 항목 ${fpGood}/${fp.effects.length}` : ''} />
            : <Stat label="한 끼 조화" value={m.harmony?.mean ?? '–'} sub={m.harmony ? `시설 실제 식단 ${m.harmony.model?.ref_real_mean ?? '–'}` : ''} />}
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-xs">
          {selInfo?.candidates?.length > 0 && (
            <button onClick={() => openFold('fold-select')} className="rounded-full bg-violet-50 px-3 py-1 text-violet-800 hover:bg-violet-100">
              AI 영양사 · {selInfo.mode === 'llm' ? `후보 ${selInfo.choice} 선택${selInfo.agreed_with_rule ? '' : ' (규칙 선택과 다름)'}` : '규칙 선택(A)'} →
            </button>
          )}
          {rv?.mode === 'llm' && (
            <button onClick={() => openFold('fold-review')} className="rounded-full bg-violet-50 px-3 py-1 text-violet-800 hover:bg-violet-100">
              AI 검토 · 메뉴 교체 {rv.accepted?.length || 0}건 →
            </button>
          )}
          {fp && (
            <button onClick={() => openFold('fold-plan')} className="rounded-full bg-emerald-50 px-3 py-1 text-emerald-800 hover:bg-emerald-100">
              개선안 반영 결과 →
            </button>
          )}
          <button onClick={() => openFold('fold-score')} className="rounded-full bg-navy-50 px-3 py-1 text-navy-700 hover:bg-navy-100">점수 자세히 →</button>
        </div>
      </section>

      {/* ② 식단표 */}
      <Section title="28일 일반식 식단표"
        right={<>
          {[1, 2, 3, 4].map((w) => (
            <button key={w} onClick={() => setWeek(w)} className={`px-3 py-1 rounded-full text-xs font-semibold ${week === w ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>{w}주</button>
          ))}
          <label className="ml-1 flex items-center gap-1 text-xs text-navy-700">
            <input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> 영양 수치
          </label>
          {nEdits > 0 && <>
            <span className="text-xs text-amber-700">수정 {nEdits}건</span>
            <button className="btn-ghost text-xs" onClick={() => setEdits({})}>취소</button>
            <button className="btn-primary text-xs" disabled={saving} onClick={saveEdits}>{saving ? '저장 중…' : '수정본 계산'}</button>
          </>}
        </>}>
        <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
          <span>메뉴를 누르면 같은 칸의 다른 후보로 바꿀 수 있어요</span>
          {Object.keys(planTags).length > 0 && <>
            <span><span className="text-emerald-600">●</span> 개선안으로 더 고른 메뉴</span>
            <span><span className="text-rose-500">●</span> 개선안이 줄이려는 메뉴</span>
          </>}
          {Object.keys(reviewed).length > 0 && <span><span className="rounded bg-violet-50 px-1 text-violet-900">보라</span> AI 검토로 바뀐 메뉴</span>}
          <span><span className="rounded bg-amber-50 px-1 text-amber-900">노랑</span> 지금 고치는 중</span>
        </div>
        <div className="overflow-x-auto">
          <table className={`w-full text-[13px] ${detail ? 'min-w-[1080px]' : 'min-w-[860px]'}`}>
            <thead>
              <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                <th className="py-2 pr-2 w-12">일차</th><th className="py-2 pr-2 w-10">끼니</th>
                {SLOTS.map((s) => <th key={s} className="py-2 pr-2">{s}</th>)}
                {detail ? <>
                  <th className="py-2 pr-2 text-right">열량</th><th className="py-2 pr-2 text-right">나트륨</th><th className="py-2 pr-2 text-right">단백질</th>
                  <th className="py-2 pr-2 text-right" title="실제 요양원 식단표로 학습한 국·주찬·부찬 조합 점수 (0~1)">조화</th>
                  <th className="py-2">다진찬 주의</th>
                </> : <th className="py-2">확인</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.일차 + r.끼니} className={`border-b align-top ${r.끼니 === '저녁' ? 'border-navy-100' : 'border-navy-50'}`}>
                  <td className="py-1.5 pr-2 font-semibold text-navy-900 whitespace-nowrap">{r.끼니 === '아침' ? r.일차 : ''}</td>
                  <td className="py-1.5 pr-2 text-muted whitespace-nowrap">{r.끼니}</td>
                  {SLOTS.map((s) => {
                    const k = `${r.일차}|${r.끼니}|${s}`
                    const v = edits[k] ?? r[s]
                    const isEdit = editing && editing.k === k
                    return (
                      <td key={s} className="py-1.5 pr-2">
                        {isEdit ? (
                          <select autoFocus className="form-select !py-1 !text-xs" value={v}
                            onBlur={() => setEditing(null)}
                            onChange={(e) => { setEdits({ ...edits, [k]: e.target.value }); setEditing(null) }}>
                            {!options && <option>불러오는 중…</option>}
                            {(options?.[SLOT_CAT[s]] || []).map((o) => <option key={o} value={o}>{o}</option>)}
                          </select>
                        ) : (
                          <button disabled={String(r[s]).startsWith('-(')} onClick={() => openEdit({ k })}
                            title={!edits[k] && reviewed[k] ? `AI 검토로 바뀜: ${reviewed[k].current} → ${reviewed[k].replace_with} (${reviewed[k].problem || ''})` : undefined}
                            className={`text-left rounded px-1 -mx-1 hover:bg-navy-50 ${edits[k] ? 'bg-amber-50 text-amber-900 font-semibold' : reviewed[k] ? 'bg-violet-50 text-violet-900' : ''}`}>{v}</button>
                        )}
                        {!isEdit && planTags[v] && (
                          <span className={`ml-0.5 text-[9px] align-top cursor-help ${planTags[v].some((t) => t.kind === 'limit') ? 'text-rose-500' : 'text-emerald-600'}`}
                            title={`시설 개선안: ${planTags[v].map((t) => t.label).join(', ')}`}>●</span>
                        )}
                      </td>
                    )
                  })}
                  {detail ? <>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{r['열량(kcal)']}</td>
                    <td className={`py-1.5 pr-2 text-right tabular-nums ${r['나트륨(mg)'] > 600 ? 'text-rose-600 font-semibold' : ''}`}>{r['나트륨(mg)']}</td>
                    <td className="py-1.5 pr-2 text-right tabular-nums">{r['단백질(g)']}</td>
                    <td className={`py-1.5 pr-2 text-right tabular-nums ${r.조화 != null && r.조화 < 0.4 ? 'text-amber-700 font-semibold' : 'text-muted'}`}>{r.조화 != null ? r.조화.toFixed(2) : '–'}</td>
                    <td className="py-1.5 text-[11px] text-muted">{r.다진찬주의 === '-' ? '' : r.다진찬주의}</td>
                  </> : (
                    <td className="py-1.5 whitespace-nowrap">
                      {flags(r).map((x) => <span key={x.t} title={x.tip} className={`mr-1 cursor-help rounded px-1.5 py-0.5 text-[10px] font-semibold ${x.c}`}>{x.t}</span>)}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!detail && <p className="mt-2 text-[11px] text-muted">확인 칸: 나트륨↑ 끼니 600mg 초과 · 조화↓ 한 끼 조합 점수 0.4 미만 · 다진찬 다진찬으로 만들기 어려운 메뉴 포함 (마우스를 올리면 자세히). 수치는 ‘영양 수치’를 켜면 보여요.</p>}
      </Section>

      {/* ③ 접어 둔 상세 */}
      {fp && (
        <Fold id="fold-plan" title="시설 개선안 반영 결과" summary={fpGood != null ? `${fp.items?.length || 0}건 반영 · 비교 기준보다 나아진 항목 ${fpGood}/${fp.effects.length}` : `${fp.items?.length || 0}건 반영`}>
          <FacilityPlanResult fp={fp} bare />
        </Fold>
      )}
      {(selInfo?.candidates?.length > 0 || run.parent_run_id) && (
        <Fold id="fold-select" title="AI 영양사 선택" summary={selInfo?.summary}>
          <SelectionPanel run={run} onEdited={onEdited} setErr={setErr} bare />
        </Fold>
      )}
      {rv && (
        <Fold id="fold-review" title="AI 식단 검토" summary={rv.mode === 'llm' ? `제안 ${rv.n_suggested}건 · 반영 ${rv.accepted?.length || 0}건 · 거절 ${rv.rejected?.length || 0}건` : (rv.note || '검토하지 않음')}>
          <ReviewPanel run={run} onEdited={onEdited} setErr={setErr} bare />
        </Fold>
      )}
      <Fold id="fold-score" title="점수 자세히" summary="목적함수 4개 · 조화 · 파레토 해 품질 · 영양 위반 기여도 · 식단 규칙 · 재고 활용">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {(() => {
            const f2 = sel['f2_비용'] ?? sel['f2_예산·재고']
            const isNew = sel['f3_다양성'] != null
            const p3 = m.objective_parts?.f3 || {}, p4 = m.objective_parts?.f4 || {}
            return (<>
              <Stat label="f1 영양 위반 ↓" value={f1} sub="낮을수록 좋음 · 0.3 이하 목표" tone={f1 <= 0.3 ? 'bg-emerald-50' : 'bg-amber-50'} />
              <Stat label="f2 비용 ↓" value={f2} sub={m.inventory_unused != null ? `예산 초과 + 재고 미활용 ${m.inventory_unused}` : '예산 초과 (재고 미입력)'} />
              {isNew ? (<>
                <Stat label="f3 반복·편중 ↓" value={sel['f3_다양성']} sub={`낮을수록 다양함 · 반복 ${p3['14일 반복'] ?? '–'} · 편중 ${p3['편중(1-Simpson)'] ?? '–'}`} />
                <Stat label="f4 조화 문제 ↓" value={sel['f4_조화']} sub={`낮을수록 잘 어울림 · 선호 ${p4['시설 선호(섭취율)'] ?? '–'} · 다진찬 ${p4['다진찬 부적합'] ?? '–'}`} />
              </>) : (<>
                <Stat label="f3 다양성·선호 (이전)" value={sel['f3_다양성·선호']} sub="이전 목적함수 — 다시 설계하면 새 기준" />
                <Stat label="f4 패턴 위반 (이전)" value={sel['f4_패턴위반']} sub="이전 목적함수" />
              </>)}
            </>)
          })()}
          {m.harmony && (
            <Stat label="한 끼 조화 ↑" value={m.harmony.mean} sub={`시설 실제 식단 ${m.harmony.model?.ref_real_mean ?? '–'} · 무작위 ${m.harmony.model?.ref_random_mean ?? '–'} · 낮은 끼니 ${m.harmony.low_meals}`}
              tone={m.harmony.mean >= (m.harmony.model?.ref_real_mean || 0.55) - 0.02 ? 'bg-emerald-50' : 'bg-amber-50'} />
          )}
          {m.harmony && (
            <Stat label="시설 스타일 유사도 ↑" value={m.harmony.style_similarity} sub={`끼니별 국 종류·조리법·주재료 분포 (${m.harmony.model?.facility} ${m.harmony.model?.n_meals}끼 학습)`} />
          )}
          <Stat label="파레토 해 품질(HV) ↑" value={m.front?.hv?.toFixed?.(3) ?? '–'} sub={m.front ? `비지배해 ${m.front.n_nondom}개 · f1 통과 ${m.front.f1_pass_rate}%` : '수정본은 계산 안 함'} />
          <Stat label="설계 어르신" value={run.result?.residents?.length} unit="명" sub={m.optimize_sec ? `최적화 ${m.optimize_sec}초` : run.parent_run_id ? '영양사 수정본' : ''} />
        </div>
        <div className="mt-4 grid md:grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-xs font-bold text-muted mb-1">f1 영양소별 기여도</p>
            {Object.entries(m.nutrition_breakdown || {}).slice(0, 10).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5"><span>{k}</span><span className="tabular-nums">{v}</span></div>
            ))}
          </div>
          <div>
            <p className="text-xs font-bold text-muted mb-1">식단 규칙 점검 (84끼)</p>
            {Object.entries(m.pattern || {}).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs py-0.5"><span>{k.replaceAll('_', ' ')}</span><span className="tabular-nums">{v}</span></div>
            ))}
            {m.repeat_repair?.changes?.length > 0 && (
              <details className="mt-2 text-[11px]">
                <summary className="cursor-pointer text-navy-700">반복 메뉴 보정 {m.repeat_repair.changes.length}건 (3일 안 반복 → 같은 분류 다른 메뉴)</summary>
                {m.repeat_repair.changes.map((c, k) => (
                  <p key={k} className="text-muted">{c.일차} {c.끼니} {c.칸}: {c.기존} → <b className="text-navy-800">{c.변경}</b></p>
                ))}
              </details>
            )}
            {m.selection_rule && <p className="mt-2 text-[11px] text-muted">해 선택: {m.selection_rule}</p>}
          </div>
          <div>
            <p className="text-xs font-bold text-muted mb-1">재고 활용 (유통기한 전 사용)</p>
            {(m.inventory || []).map((x) => (
              <div key={x.식재료명} className="flex justify-between text-xs py-0.5"><span>{x.식재료명} <span className="text-muted">D-{x.남은일수}</span></span><span className="tabular-nums">{x['활용률(%)']}%</span></div>
            ))}
            {!m.inventory && <p className="text-xs text-muted">재고를 입력하면 표시됩니다.</p>}
          </div>
        </div>
      </Fold>
    </div>
  )
}

/* ─────────────────────────── ② 개인 배식표 ─────────────────────────── */

function ServingTab({ run }) {
  const residents = run.result?.residents || []
  const [q, setQ] = useState('')
  const [eid, setEid] = useState(residents[0]?.elderly_id || null)
  const [meals, setMeals] = useState(null)
  const [week, setWeek] = useState(1)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!eid) return
    setMeals(null); setErr('')
    api.get(`/care/diet/runs/${run.id}/servings/${eid}`).then((r) => setMeals(r.data.meals)).catch((e) => setErr(errMsg(e)))
  }, [eid, run.id])

  const list = residents.filter((r) => !q || r.display_name.includes(q))
  const me = residents.find((r) => r.elderly_id === eid)
  const shown = (meals || []).filter((x) => week === 0 || Math.ceil(dayNo(x.일차) / 7) === week)
  const s = me?.serving || {}
  const okPct = pct((s.끼니 || 0) - (s.조정불가 || 0), s.끼니)
  // 안전 확인(알레르기·연하·약물) — 영역별 평가의 Level 1 항목을 머리에 한 줄로
  const safety = ((run.result?.assessments?.[eid]?.synth?.priorities) || []).filter((i) => issueLevel(i) === 1).map((i) => i.title)
  const nOver = (meals || []).filter((x) => String(x.조정결과).startsWith('조정불가')).length

  return (
    <div className="grid md:grid-cols-[240px_1fr] gap-4">
      <div className="surface p-3 max-h-[760px] overflow-y-auto">
        <input className="form-input !py-2 mb-2" placeholder="이름 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        {list.map((r) => {
          const rs = r.serving || {}
          const p = pct((rs.끼니 || 0) - (rs.조정불가 || 0), rs.끼니)
          const on = eid === r.elderly_id
          return (
            <button key={r.elderly_id} onClick={() => setEid(r.elderly_id)}
              className={`w-full text-left rounded-xl px-3 py-2 mb-1 ${on ? 'bg-navy-900 text-white' : 'hover:bg-navy-50'}`}>
              <span className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold">{r.display_name}</span>
                {p != null && <span className={`text-[11px] tabular-nums ${on ? 'text-navy-100' : p >= 90 ? 'text-emerald-600' : 'text-amber-700'}`}>{p}%</span>}
              </span>
              <span className={`block text-[11px] ${on ? 'text-navy-100' : 'text-muted'}`}>{r.texture}{r.no_spicy ? ' · 백김치' : ''}{r.substitutions ? ` · 대체 ${r.substitutions}` : ''}</span>
            </button>
          )
        })}
      </div>

      <div className="space-y-4 min-w-0">
        {me && (
          <section className="surface p-5">
            {/* 어르신 요약 — 배식 담당자가 먼저 알아야 할 것만 */}
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-extrabold text-navy-900">{me.display_name} 님 배식표</h3>
              <span className="badge bg-navy-50 text-navy-700">{me.type}</span>
              <span className="badge bg-sky-50 text-sky-800">{me.texture}</span>
              {me.no_spicy && <span className="badge bg-sky-50 text-sky-800">매운 음식 불가 · 백김치</span>}
              {(me.diseases || []).map((d) => <span key={d} className="badge bg-slate-100 text-slate-600">{d}</span>)}
            </div>
            {safety.length > 0 && (
              <p className="mt-2 rounded-xl bg-rose-50 px-3 py-2 text-xs text-rose-800">
                <b>안전 확인</b> · {safety.join(' · ')} <span className="text-rose-600">— 자세한 내용은 아래 ‘이렇게 정한 근거’</span>
              </p>
            )}
            <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span><span className="text-muted text-xs mr-1">목표 열량</span><b className="tabular-nums">{Math.round(me.target_energy)}</b><span className="text-xs text-muted">kcal/끼</span></span>
              <span><span className="text-muted text-xs mr-1">나트륨 상한</span><b className="tabular-nums">{me.sodium_max}</b><span className="text-xs text-muted">mg/끼</span></span>
              <span><span className="text-muted text-xs mr-1">대체찬</span><b className="tabular-nums">{me.substitutions}</b><span className="text-xs text-muted">건{Object.keys(me.reasons || {}).length ? ` (${Object.entries(me.reasons).slice(0, 2).map(([k, v]) => `${k} ${v}`).join(', ')})` : ''}</span></span>
              <span><span className="text-muted text-xs mr-1">기준 충족</span><b className={`tabular-nums ${okPct >= 90 ? 'text-emerald-700' : 'text-amber-700'}`}>{okPct ?? '–'}%</b></span>
            </div>

            <div className="mt-4 mb-2 flex flex-wrap items-center gap-1.5">
              {[1, 2, 3, 4].map((w) => (
                <button key={w} onClick={() => setWeek(w)} className={`px-3 py-1 rounded-full text-xs font-semibold ${week === w ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>{w}주</button>
              ))}
              <button onClick={() => setWeek(0)} className={`px-3 py-1 rounded-full text-xs font-semibold ${week === 0 ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>28일 전체</button>
              {meals && nOver > 0 && <span className="ml-auto text-[11px] text-amber-700">기준 일부 초과 끼니 {nOver}끼</span>}
            </div>
            {err && <p className="text-sm text-rose-700">{err}</p>}
            {!meals ? <p className="text-sm text-muted">불러오는 중…</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px] min-w-[900px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                      <th className="py-2 pr-2 w-12">일차</th><th className="py-2 pr-2 w-10">끼니</th>
                      {SLOTS.map((sl) => <th key={sl} className="py-2 pr-2">{sl}</th>)}
                      <th className="py-2 pr-2 text-right">열량</th><th className="py-2 pr-2 text-right">나트륨</th>
                      <th className="py-2 text-center">기준</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((x) => {
                      const ratio = Object.fromEntries((x.칸별비율 || '').split(' ').map((t) => {
                        const mm = t.match(/^(밥|국|주찬|부찬1|부찬2|김치)([\d.]+)/); return mm ? [mm[1], mm[2]] : [t, '']
                      }))
                      const over = String(x.조정결과).startsWith('조정불가')
                      return (
                        <tr key={x.일차 + x.끼니} className={`border-b align-top ${x.끼니 === '저녁' ? 'border-navy-100' : 'border-navy-50'}`}>
                          <td className="py-1.5 pr-2 font-semibold text-navy-900 whitespace-nowrap">{x.끼니 === '아침' || week === 0 ? x.일차 : ''}</td>
                          <td className="py-1.5 pr-2 text-muted">{x.끼니}</td>
                          {SLOTS.map((sl) => {
                            const sub = (x.대체 || []).includes(sl)
                            const form = (x.식사형태변경 || []).includes(sl)
                            const g = x[sl]
                            const r = ratio[sl] ? Number(ratio[sl]) : null
                            return (
                              <td key={sl} className="py-1.5 pr-2">
                                <span className={`block leading-5 ${sub ? 'text-emerald-800 font-semibold' : form ? 'text-sky-800 font-semibold' : 'text-navy-900'}`}>
                                  {x.메뉴?.[sl]}
                                  {sub && <span className="ml-1 rounded bg-emerald-50 px-1 text-[10px] font-semibold text-emerald-700">대체</span>}
                                </span>
                                <span className="text-[11px] text-muted tabular-nums">
                                  {g ? `${g}g` : '미배식'}
                                  {g && r != null && r !== 1 && <span className={`ml-1 font-semibold ${r < 1 ? 'text-amber-700' : 'text-sky-700'}`}>×{r}</span>}
                                </span>
                              </td>
                            )
                          })}
                          <td className="py-1.5 pr-2 text-right tabular-nums">{x.예상열량}</td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">{x.예상나트륨}</td>
                          <td className="py-1.5 text-center" title={over ? `조정 결과: ${x.조정결과}` : '개인 기준 충족'}>
                            {over ? <span className="text-amber-700 text-xs font-semibold">⚠</span> : <span className="text-emerald-600 text-xs">✓</span>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <p className="mt-2 text-[11px] text-muted">
                  <span className="text-emerald-700 font-semibold">초록·대체</span> 고령친화식품 대체(1인분 그대로) · <span className="text-sky-800 font-semibold">파랑</span> 죽·백김치 등 식사형태 변경 ·
                  배식량은 기본 1인분이고 다를 때만 <span className="text-amber-700 font-semibold">×0.5</span>처럼 표시 · ⚠ 일부 영양 기준 초과(마우스를 올리면 자세히)
                </p>
              </div>
            )}
          </section>
        )}
        {me && (
          <Fold title="이렇게 정한 근거" summary="영역별 AI 평가 · 우선순위 · 개인 영양 기준">
            <AgentPanel a={run.result?.assessments?.[eid]} />
          </Fold>
        )}
        {me && (
          <Fold title="AI 영양 관리 계획" summary={run.result?.care_plans?.[eid] ? '작성됨' : '평가 · 영양 진단 · 중재 · 모니터링 — 필요할 때 작성'}>
            <CarePlan run={run} eid={eid} setErr={setErr} bare />
          </Fold>
        )}
        <LabelPrint run={run} />
      </div>
    </div>
  )
}

/* ─────────────────────────── ③ 주간 발주 ─────────────────────────── */

const won = (v) => (v == null ? '–' : `${Math.round(v).toLocaleString()}원`)
const kg = (g) => (g == null ? '–' : g >= 1000 ? `${(g / 1000).toFixed(1)}kg` : `${Math.round(g)}g`)

function downloadCsv(filename, rows, cols) {
  const esc = (v) => { const t = v == null ? '' : String(v); return /[",\n]/.test(t) ? `"${t.replaceAll('"', '""')}"` : t }
  const body = [cols.map((c) => c.label).join(','), ...rows.map((r) => cols.map((c) => esc(c.get(r))).join(','))].join('\n')
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' })
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}

function PurchaseTab({ run }) {
  const pu = run.result?.purchase
  const [wi, setWi] = useState(0)
  const [q, setQ] = useState('')
  const [onlyBuy, setOnlyBuy] = useState(true)
  if (!pu?.weeks?.length) {
    return <div className="surface p-10 text-center text-sm text-muted">이 설계에는 주간 발주 계산이 없습니다. 식단 설계를 다시 실행하면 함께 계산됩니다.</div>
  }
  const w = pu.weeks[wi]
  const t = w.합계
  const ing = w.식재료.filter((r) => (!onlyBuy || r['구매량(g)'] > 0) && (!q || r.식재료명.includes(q) || (r.상품명 || '').includes(q)))
  const total = (t.식재료_금액 || 0) + (t.제품_금액 || 0)

  const exportWeek = () => {
    const rows = [
      ...w.식재료.filter((r) => r['구매량(g)'] > 0).map((r) => ({ 구분: '식재료', 품목: r.식재료명, 상품명: r.상품명, 규격: r['규격(g)'], 필요: r['필요량(g)'], 재고: r['재고사용(g)'], 구매: r['구매량(g)'], 수량: r.수량, 단가: r.단가, 금액: r.금액 })),
      ...w.제품.map((r) => ({ 구분: '고령친화식품', 품목: r.제품, 상품명: `${r.업체 || ''} ${r.제품}`.trim(), 규격: r['포장(g)'], 필요: r['필요량(g)'], 재고: 0, 구매: r['필요량(g)'], 수량: r.수량, 단가: r.단가, 금액: r.금액 })),
    ]
    downloadCsv(`발주_${w.주차}주차_${w.기간 || w.일차}.csv`, rows, [
      { label: '주차', get: () => w.주차 }, { label: '입고일', get: () => w.입고일 || '' }, { label: '구분', get: (r) => r.구분 },
      { label: '품목', get: (r) => r.품목 }, { label: '상품명', get: (r) => r.상품명 }, { label: '규격(g)', get: (r) => r.규격 },
      { label: '필요량(g)', get: (r) => r.필요 }, { label: '재고사용(g)', get: (r) => r.재고 }, { label: '구매량(g)', get: (r) => r.구매 },
      { label: '수량', get: (r) => r.수량 }, { label: '단가(원)', get: (r) => r.단가 }, { label: '금액(원)', get: (r) => r.금액 },
    ])
  }

  return (
    <div className="space-y-4">
      <Section title="주간 발주"
        right={<>
          {pu.weeks.map((x, i) => (
            <button key={x.주차} onClick={() => setWi(i)} className={`px-3 py-1 rounded-full text-xs font-semibold ${wi === i ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>
              {x.주차}주차{x.기간 ? ` · ${x.기간}` : ''}
            </button>
          ))}
          <button className="btn-secondary text-xs" onClick={exportWeek}>CSV 내려받기</button>
        </>}>
        <p className="mb-3 text-xs text-muted leading-5">
          {w.일차}{w.입고일 ? ` · ${w.입고일} 입고 기준` : ' · 재고 화면에서 식단 1일차 날짜를 넣으면 날짜로 표시됩니다'}.
          개인별 배식량(대체찬·죽·백김치 반영)으로 식재료 실사용량을 합산하고, 유통기한이 남은 재고를 먼저 뺀 양입니다. 국·반찬 양념은 저염 조리 감량(40%)을 반영했습니다.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="예상 발주 금액" value={total ? Math.round(total).toLocaleString() : '–'} unit="원"
            sub={t.단가미등록_품목 ? `단가 미등록 ${t.단가미등록_품목}품목 제외` : '전체 단가 반영'} tone="bg-navy-50" />
          <Stat label="식재료" value={t.식재료_품목} unit="품목" sub={`${won(t.식재료_금액)}${t.단가미등록_품목 ? ` · 미등록 ${t['단가미등록_구매량(kg)']}kg` : ''}`} />
          <Stat label="고령친화식품" value={t.제품_팩} unit="팩" sub={`${won(t.제품_금액)} · 부가세 별도`} />
          <Stat label="재고 사용" value={t['재고사용(kg)']} unit="kg" sub="이번 주에 쓰는 기존 재고" />
        </div>
        {!pu.price_count && (
          <p className="mt-3 text-xs rounded-xl bg-amber-50 text-amber-800 px-3 py-2">
            식재료 단가가 아직 등록되지 않아 구매량만 표시됩니다. 식재료 상품·단가(ingredient_prices.json)를 넣으면 상품명·수량·금액이 함께 나옵니다.
          </p>
        )}
      </Section>

      <Section title={`식재료 (${ing.length})`}
        right={<>
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={onlyBuy} onChange={(e) => setOnlyBuy(e.target.checked)} />구매 필요한 것만
          </label>
          <input className="form-input !py-1.5 !w-40" placeholder="식재료 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        </>}>
        <Table rows={ing} minW={900} rowKey={(r) => r.식재료명} cols={[
          { key: '식재료명', label: '식재료', cls: 'font-semibold text-navy-900' },
          { key: '필요량(g)', label: '필요량', right: true, render: (r) => kg(r['필요량(g)']) },
          { key: '재고사용(g)', label: '재고 사용', right: true, render: (r) => (r['재고사용(g)'] ? <span className="text-emerald-700">{kg(r['재고사용(g)'])}</span> : '–') },
          { key: '구매량(g)', label: '구매량', right: true, render: (r) => <b>{kg(r['구매량(g)'])}</b> },
          { key: '상품명', label: '구매 상품', render: (r) => r.상품명 ? <span>{r.상품명}<span className="text-muted"> · {kg(r['규격(g)'])}</span></span> : <span className="text-muted">단가 미등록</span> },
          { key: '수량', label: '수량', right: true, render: (r) => (r.수량 ? `${r.수량}개` : '–') },
          { key: '단가', label: '단가', right: true, render: (r) => won(r.단가) },
          { key: '금액', label: '금액', right: true, render: (r) => (r.금액 ? won(r.금액) : '–') },
          { key: '메뉴수', label: '쓰는 메뉴', right: true },
        ]} />
      </Section>

      <Section title={`고령친화식품 (${w.제품.length})`}>
        <Table rows={w.제품} minW={760} empty="이번 주 대체찬이 없습니다." cols={[
          { key: '제품', label: '제품', cls: 'font-semibold text-navy-900' }, { key: '업체', label: '업체', cls: 'text-muted' },
          { key: '인분', label: '인분', right: true }, { key: '필요량(g)', label: '필요량', right: true, render: (r) => kg(r['필요량(g)']) },
          { key: '포장(g)', label: '포장', right: true, render: (r) => (r['포장(g)'] ? `${kg(r['포장(g)'])}(5인분)` : '–') },
          { key: '수량', label: '수량', right: true, render: (r) => (r.수량 != null ? `${r.수량}팩` : '–') },
          { key: '단가', label: '단가', right: true, render: (r) => won(r.단가) },
          { key: '금액', label: '금액', right: true, render: (r) => <b>{won(r.금액)}</b> },
        ]} />
      </Section>
    </div>
  )
}

/* ─────────────────────────── ④ 대체찬·죽 ─────────────────────────── */

function SubsTab({ run }) {
  const res = run.result || {}
  const subs = res.substitutions || []
  const [day, setDay] = useState('all')
  const days = [...new Set(subs.map((s) => s.day))].sort((a, b) => dayNo(a) - dayNo(b))
  const shown = subs.filter((s) => day === 'all' || s.day === day)
  const orders = (res.orders || []).filter((o) => day === 'all' || o.일차 === day)
  const reasons = Object.entries(res.substitution_reasons || {}).sort((a, b) => b[1] - a[1])

  return (
    <div className="space-y-4">
      <Section title="대체 사유"
        right={<select className="form-select !py-1.5 !w-auto" value={day} onChange={(e) => setDay(e.target.value)}>
          <option value="all">28일 전체</option>
          {days.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>}>
        <div className="flex flex-wrap gap-2">
          {reasons.map(([k, v]) => <span key={k} className="badge bg-navy-50 text-navy-700">{k} {v}</span>)}
          {!reasons.length && <span className="text-sm text-muted">대체가 필요한 끼니가 없습니다.</span>}
        </div>
      </Section>

      <Section title={`대체찬 조리·배식 지침 (${shown.length}건)`}>
        <Table rows={shown} minW={960} cols={[
          { key: 'day', label: '일차' }, { key: 'meal', label: '끼니' },
          { key: 'display_name', label: '어르신', cls: 'font-semibold text-navy-900 whitespace-nowrap' },
          { key: 'type', label: '유형' }, { key: 'texture', label: '식사형태' }, { key: 'slot', label: '칸' },
          { key: 'orig', label: '기존 메뉴', cls: 'text-muted' },
          { key: 'product', label: '대체 제품', cls: 'font-semibold text-emerald-800' },
          { key: 'cook', label: '조리법' }, { key: 'grams', label: '1인분(g)', right: true },
          { key: 'reason', label: '사유', cls: 'text-xs text-muted' },
        ]} />
      </Section>

      <div className="grid md:grid-cols-2 gap-4">
        <Section title="일자별 발주량">
          <Table rows={orders} minW={420} cols={[
            { key: '일차', label: '일차' }, { key: '제품', label: '제품', cls: 'font-semibold text-navy-900' },
            { key: '인분', label: '인분', right: true }, { key: '총량(g)', label: '총량(g)', right: true },
          ]} />
        </Section>
        <Section title="28일 제품별 합계">
          <Table rows={res.product_totals} minW={420} cols={[
            { key: '제품', label: '제품', cls: 'font-semibold text-navy-900' }, { key: '업체', label: '업체', cls: 'text-muted' },
            { key: '인분', label: '인분', right: true }, { key: '총량(kg)', label: '총량(kg)', right: true },
          ]} />
        </Section>
      </div>

      <Section title={`안전 확인 목록 — 약물·알레르기 (${(res.safety_flags || []).length})`}>
        <p className="mb-2 text-xs text-muted leading-5">
          약물·알레르기 에이전트가 찾은 '피할 식재료'가 든 반찬은 고령친화식품으로 먼저 바꿉니다. 아래는 맞는 제품이 없거나(국·김치 칸 등)
          끼니당 2칸을 넘어 그대로 남은 반찬입니다. 같은 분류에서 피할 식재료가 없는 메뉴를 추천합니다.
        </p>
        <Table rows={(res.safety_flags || []).filter((s) => day === 'all' || s.day === day)} minW={860} empty="남은 안전 문제가 없습니다." cols={[
          { key: 'day', label: '일차' }, { key: 'meal', label: '끼니' },
          { key: 'display_name', label: '어르신', cls: 'font-semibold text-navy-900 whitespace-nowrap' },
          { key: 'slot', label: '칸' }, { key: 'menu', label: '메뉴', cls: 'text-rose-700 font-semibold' },
          { key: 'reason', label: '사유', cls: 'text-xs' },
          { key: 'alternatives', label: '대신 낼 수 있는 메뉴', cls: 'text-xs text-emerald-800', render: (r) => (r.alternatives || []).join(' · ') || '–' },
        ]} />
      </Section>

      <Section title="죽식 어르신 영양죽 계획 (아침은 흰죽)">
        <Table rows={res.porridge} minW={480} empty="죽식 어르신이 없습니다." cols={[
          { key: '일차', label: '일차' }, { key: '끼니', label: '끼니' },
          { key: '죽', label: '영양죽', cls: 'font-semibold text-navy-900' },
          { key: '사용 재고', label: '사용 재고 (일반식에서 남은 재고)', cls: 'text-xs text-muted' },
        ]} />
      </Section>
    </div>
  )
}

/* ─────────────────────────── 배식 라벨 출력 ─────────────────────────── */

// A4 라벨지 (열 × 행, 라벨 크기 mm). 여백은 자동으로 가운데 맞춤 + '위치 보정'으로 미세 조정
const LABEL_SHEETS = {
  '2x5': { label: 'A4 2×5칸 (99 × 57mm)', cols: 2, rows: 5, w: 99.1, h: 57, font: 12 },
  '2x6': { label: 'A4 2×6칸 (99 × 46mm)', cols: 2, rows: 6, w: 99.1, h: 46, font: 10 },
  '2x7': { label: 'A4 2×7칸 (99 × 38mm)', cols: 2, rows: 7, w: 99.1, h: 38.1, font: 8.5 },
  '3x7': { label: 'A4 3×7칸 (63.5 × 38mm)', cols: 3, rows: 7, w: 63.5, h: 38.1, font: 8 },
}
const escHtml = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))

function LabelPrint({ run }) {
  const days = [...new Set((run.menu || []).map((r) => r.일차))].sort((a, b) => dayNo(a) - dayNo(b))
  const [open, setOpen] = useState(false)
  const [day, setDay] = useState(days[0] || '1일')
  const [meal, setMeal] = useState('아침')
  const [sheet, setSheet] = useState('2x5')
  const [tag, setTag] = useState('texture')       // 괄호 안: texture(식사형태) | type(질환 유형) | both
  const [order, setOrder] = useState('id')
  const [star, setStar] = useState(false)         // 대체 반찬 ★
  const [grams, setGrams] = useState(false)       // 배식량(배)
  const [border, setBorder] = useState(true)      // 칸 테두리 (라벨지 위치 맞출 때)
  const [dx, setDx] = useState(0)
  const [dy, setDy] = useState(0)
  const [labels, setLabels] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!open) return
    setBusy(true); setErr(''); setLabels(null)
    api.get(`/care/diet/runs/${run.id}/labels`, { params: { day, meal } })
      .then((r) => setLabels(r.data.labels)).catch((e) => setErr(errMsg(e))).finally(() => setBusy(false))
  }, [open, day, meal, run.id])

  const tagOf = (x) => tag === 'type' ? x.type : tag === 'both' ? `${x.texture} · ${x.type}` : x.texture
  const sorted = (labels || []).slice().sort((a, b) =>
    (MEALS.indexOf(a.meal) - MEALS.indexOf(b.meal)) ||
    (order === 'name' ? String(a.name).localeCompare(String(b.name), 'ko')
      : order === 'texture' ? String(a.texture).localeCompare(String(b.texture), 'ko') || String(a.id).localeCompare(String(b.id))
        : String(a.id).localeCompare(String(b.id), 'ko', { numeric: true })))
  const itemText = (i) => `${star && i.sub ? '★ ' : ''}${i.name}${grams && i.ratio != null && i.ratio !== 1 ? ` (×${i.ratio})` : ''}`

  const print = () => {
    const S = LABEL_SHEETS[sheet]
    const gapX = S.cols > 1 ? Math.max(0, (210 - 8 - S.cols * S.w) / (S.cols - 1)) : 0
    const gx = Math.min(gapX, 3)
    const left = (210 - S.cols * S.w - (S.cols - 1) * gx) / 2 + Number(dx || 0)
    const top = (297 - S.rows * S.h) / 2 + Number(dy || 0)
    const per = S.cols * S.rows
    const pages = []
    for (let i = 0; i < sorted.length; i += per) pages.push(sorted.slice(i, i + per))
    const card = (x) => `<div class="lb"><div class="hd">[${escHtml(x.id)}] (${escHtml(x.meal)}) <b>${escHtml(x.name)}</b> (${escHtml(tagOf(x))})</div><ul>${
      x.items.map((i) => `<li>${escHtml(itemText(i))}</li>`).join('')}</ul></div>`
    const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>배식 라벨 ${escHtml(day)} ${escHtml(meal === 'all' ? '하루' : meal)}</title>
<style>
@page { size: A4; margin: 0 }
* { box-sizing: border-box; margin: 0; padding: 0 }
body { font-family: "Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans KR", sans-serif; color: #000 }
.page { width: 210mm; height: 297mm; position: relative; page-break-after: always; overflow: hidden }
.page:last-child { page-break-after: auto }
.grid { position: absolute; left: ${left}mm; top: ${top}mm; display: grid;
  grid-template-columns: repeat(${S.cols}, ${S.w}mm); grid-auto-rows: ${S.h}mm; column-gap: ${gx}mm }
.lb { padding: 2.5mm 3.5mm; overflow: hidden; ${border ? 'outline: 0.2mm dashed #999; outline-offset: -0.1mm;' : ''} font-size: ${S.font}pt; line-height: 1.3 }
.hd { font-size: ${S.font + 0.5}pt; margin-bottom: 1mm; white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
ul { list-style: none } li::before { content: "* " } li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis }
</style></head><body>${pages.map((pg) => `<div class="page"><div class="grid">${pg.map(card).join('')}</div></div>`).join('')}
<script>window.onload = () => setTimeout(() => window.print(), 200)<\/script></body></html>`
    const w = window.open('', '_blank')
    if (!w) { setErr('팝업이 막혀 있습니다. 브라우저에서 이 사이트의 팝업을 허용해 주세요.'); return }
    w.document.open(); w.document.write(html); w.document.close()
  }

  const S = LABEL_SHEETS[sheet]
  const nPages = labels ? Math.ceil(labels.length / (S.cols * S.rows)) : 0
  return (
    <div className="surface px-5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-bold text-navy-900">배식 라벨 출력 <span className="font-normal text-xs text-muted">— 끼니별 어르신 라벨을 A4 라벨지로 인쇄</span></p>
        <button className="btn-secondary !py-1.5 text-xs" onClick={() => setOpen((o) => !o)}>{open ? '닫기' : '라벨 만들기'}</button>
      </div>
      {open && (
        <div className="mt-3 grid lg:grid-cols-[1fr_320px] gap-4">
          <div className="space-y-2 text-xs">
            <div className="flex flex-wrap gap-2 items-center">
              <select id="lb-day" className="form-select !py-1.5 !w-auto" value={day} onChange={(e) => setDay(e.target.value)}>
                {days.map((d) => <option key={d} value={d}>{d}</option>)}
              </select>
              <select id="lb-meal" className="form-select !py-1.5 !w-auto" value={meal} onChange={(e) => setMeal(e.target.value)}>
                {MEALS.map((m) => <option key={m} value={m}>{m}</option>)}
                <option value="all">하루 전체 (아침·점심·저녁)</option>
              </select>
              <select id="lb-sheet" className="form-select !py-1.5 !w-auto" value={sheet} onChange={(e) => setSheet(e.target.value)}>
                {Object.entries(LABEL_SHEETS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
              <select id="lb-order" className="form-select !py-1.5 !w-auto" value={order} onChange={(e) => setOrder(e.target.value)}>
                <option value="id">식별번호 순</option><option value="name">이름 순</option><option value="texture">식사형태별</option>
              </select>
              <select id="lb-tag" className="form-select !py-1.5 !w-auto" value={tag} onChange={(e) => setTag(e.target.value)}>
                <option value="texture">괄호: 식사형태</option><option value="type">괄호: 질환 유형</option><option value="both">괄호: 둘 다</option>
              </select>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1 items-center text-navy-800">
              <label className="flex items-center gap-1"><input id="lb-star" type="checkbox" checked={star} onChange={(e) => setStar(e.target.checked)} />대체 반찬 ★ 표시</label>
              <label className="flex items-center gap-1"><input id="lb-grams" type="checkbox" checked={grams} onChange={(e) => setGrams(e.target.checked)} />배식량(×배) 표시</label>
              <label className="flex items-center gap-1"><input id="lb-border" type="checkbox" checked={border} onChange={(e) => setBorder(e.target.checked)} />칸 테두리 (위치 맞출 때)</label>
              <span className="flex items-center gap-1">위치 보정 가로
                <input id="lb-dx" type="number" step="0.5" className="form-input !py-0.5 !w-16" value={dx} onChange={(e) => setDx(e.target.value)} />mm · 세로
                <input id="lb-dy" type="number" step="0.5" className="form-input !py-0.5 !w-16" value={dy} onChange={(e) => setDy(e.target.value)} />mm</span>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button className="btn-primary !py-1.5 text-xs" disabled={!labels?.length} onClick={print}>인쇄 ({labels?.length ?? 0}장 · A4 {nPages}쪽)</button>
              {busy && <span className="text-muted">불러오는 중…</span>}
              {err && <span className="text-rose-700">{err}</span>}
            </div>
            <p className="text-[11px] text-muted leading-5">
              인쇄 창에서 <b>배율 100%(실제 크기)</b>, 여백 '없음'으로 인쇄하세요. 처음에는 일반 종이에 테두리를 켜고 한 장 뽑아 라벨지에 겹쳐 보고, 어긋나면 위치 보정(mm)으로 맞춥니다.
              식별번호는 어르신 ID입니다. 메뉴는 대체찬·죽·백김치가 반영된 개인 메뉴이며, 일품식 끼니는 밥 칸을 뺍니다.
            </p>
          </div>
          <div>
            <p className="text-[11px] font-bold text-muted mb-1">미리보기</p>
            {(sorted.slice(0, 2)).map((x) => (
              <div key={x.id + x.meal} className="mb-2 rounded border border-dashed border-slate-400 bg-white text-black px-3 py-2 text-[12px] leading-5">
                <p className="truncate">[{x.id}] ({x.meal}) <b>{x.name}</b> ({tagOf(x)})</p>
                {x.items.map((i) => <p key={i.slot} className="truncate">* {itemText(i)}</p>)}
              </div>
            ))}
            {labels && !labels.length && <p className="text-xs text-muted">이 끼니의 배식표가 없습니다.</p>}
          </div>
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────── 대체찬 요약 (어르신별) ─────────────────────────── */

const RESOLVED_LABEL = {
  sodium: '나트륨 초과', sugar: '당류 초과', sat_fat: '포화지방 초과', fat: '지방 초과', protein: '단백질 초과',
  energy_low: '열량 부족', protein_low: '단백질 부족', fiber_low: '식이섬유 부족', potassium_low: '칼륨 부족',
  dementia: '뇌건강 식재료', safety: '안전(약물·알레르기)',
}
const splitReasons = (r) => String(r || '').split(' / ').map((x) => x.trim()).filter(Boolean)

/* 대체 전후 영양성분 (끼니 합계 · 반찬) */
const NUT_ROWS = [
  ['energy', '열량', 'kcal'], ['protein', '단백질', 'g'], ['sugar', '당류', 'g'], ['sodium', '나트륨', 'mg'],
  ['sat_fat', '포화지방', 'g'], ['fat', '지방', 'g'], ['fiber', '식이섬유', 'g'], ['potassium', '칼륨', 'mg'],
]
const RESOLVE_NUT = { sodium: 'sodium', sugar: 'sugar', sat_fat: 'sat_fat', fat: 'fat', protein: 'protein',
  energy_low: 'energy', protein_low: 'protein', fiber_low: 'fiber', potassium_low: 'potassium' }
const fmtN = (v, u) => (v == null ? '–' : `${u === 'mg' || u === 'kcal' ? Math.round(v).toLocaleString() : Number(v).toFixed(1)}`)
const limText = (l, u) => (!l ? '–' : [l.min != null ? `≥${fmtN(l.min, u)}` : null, l.max != null ? `≤${fmtN(l.max, u)}` : null].filter(Boolean).join(' '))
// 대체 판단과 같은 규칙: 기준을 10% 넘게 벗어나면 위반
const nutState = (v, l) => {
  if (v == null || !l) return ''
  if (l.max != null && v > l.max * 1.1) return 'over'
  if (l.min != null && v < l.min * 0.9) return 'under'
  return 'ok'
}
const NUT_CLS = { over: 'text-rose-700 font-semibold', under: 'text-amber-700 font-semibold', ok: 'text-emerald-700', '': 'text-navy-900' }

function nutChanges(s) {
  const n = s.nut
  if (!n || !n.meal_after) return []
  const keys = [...new Set((s.resolved || []).map((k) => RESOLVE_NUT[k]).filter(Boolean))]
  return keys.map((k) => {
    const row = NUT_ROWS.find((r) => r[0] === k)
    return `${row[1]} ${fmtN(n.meal_before[k], row[2])}→${fmtN(n.meal_after[k], row[2])}${row[2]}`
  })
}

function NutCompare({ s, lim }) {
  const n = s.nut
  if (!n) return <p className="text-xs text-muted py-2">이 설계 결과에는 대체 전후 영양 기록이 없습니다. 식단 설계를 다시 실행하면 보입니다.</p>
  const miss = new Set(n.meal_after?.missing || [])
  const sv = n.served || {}
  const cols = ['항목', '개인 기준', '대체 전 끼니', '대체 후 끼니', '배식 후 (최종)', `기존 반찬 · ${s.orig}`, `대체 제품 · ${s.product}`]
  return (
    <div className="py-2">
      <table className="w-full text-xs tabular-nums" style={{ minWidth: 760 }}>
        <thead><tr className="text-muted border-b border-navy-100">
          {cols.map((h, i) => <th key={i} className={`py-1 pr-2 font-semibold ${i ? 'text-right' : 'text-left'} ${i >= 5 ? 'max-w-[160px] truncate' : ''}`} title={h}>{h}</th>)}
        </tr></thead>
        <tbody>
          {NUT_ROWS.map(([k, label, u]) => {
            const l = lim?.[k]
            const b = n.meal_before?.[k], a = n.meal_after?.[k], f = sv[k]
            return (
              <tr key={k} className="border-b border-navy-50 last:border-0">
                <td className="py-1 pr-2 text-left text-navy-900">{label} <span className="text-muted">({u})</span></td>
                <td className="py-1 pr-2 text-right text-muted">{limText(l, u)}</td>
                <td className={`py-1 pr-2 text-right ${NUT_CLS[nutState(b, l)]}`}>{fmtN(b, u)}</td>
                <td className={`py-1 pr-2 text-right ${NUT_CLS[nutState(a, l)]}`}>{fmtN(a, u)}{miss.has(k) ? <span className="text-muted">*</span> : ''}</td>
                <td className={`py-1 pr-2 text-right ${f == null ? 'text-slate-300' : NUT_CLS[nutState(f, l)]}`}>{fmtN(f, u)}</td>
                <td className="py-1 pr-2 text-right text-muted">{fmtN(n.orig?.[k], u)}</td>
                <td className="py-1 pr-2 text-right text-muted">{fmtN(n.product?.[k], u)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="mt-1.5 text-[11px] text-muted leading-5">
        끼니 합계는 이 어르신의 배식 비율(×{n.ratio})을 적용한 양으로, 대체 판단에 쓴 값입니다. 대체 후 끼니 = 이 끼니의 대체를 모두 마친 뒤.
        배식 후 = 배식량 조정까지 마친 최종 값 (배식 단계는 열량·단백질·나트륨만 계산{sv.result ? ` · ${sv.result}` : ''}{sv.portions ? ` · ${sv.portions}` : ''}).
        반찬 칸은 1인분 원래 양입니다. <span className="text-rose-700">빨강</span> 상한 초과 · <span className="text-amber-700">주황</span> 하한 부족 (기준을 10% 넘게 벗어남).
        {miss.size > 0 && ' * 제품에 영양 정보가 없어 0으로 더한 값 (실제보다 작게 보일 수 있음).'}
      </p>
    </div>
  )
}

function SubsSummaryTab({ run }) {
  const res = run.result || {}
  const subs = res.substitutions || []
  const residents = res.residents || []
  const [q, setQ] = useState('')
  const [type, setType] = useState('all')
  const [reason, setReason] = useState('all')
  const [open, setOpen] = useState({})
  const [nutOpen, setNutOpen] = useState({})

  const types = [...new Set(residents.map((r) => r.type).filter(Boolean))].sort()
  const allReasons = Object.entries(res.substitution_reasons || {}).sort((a, b) => b[1] - a[1]).map(([k]) => k)
  const match = (s) => (reason === 'all' || splitReasons(s.reason).includes(reason))
  const byRes = useMemo(() => {
    const m = {}
    for (const s of subs) (m[s.elderly_id] ||= []).push(s)
    return m
  }, [run.id])
  const rows = residents
    .filter((r) => (type === 'all' || r.type === type) && (!q || String(r.display_name || '').includes(q.trim())))
    .map((r) => ({ ...r, list: (byRes[r.elderly_id] || []).filter(match) }))
  const withSubs = rows.filter((r) => r.list.length).sort((a, b) => b.list.length - a.list.length)
  const without = rows.filter((r) => !r.list.length)
  const shown = withSubs.flatMap((r) => r.list)

  // 유형 × 사유 표
  const matrix = useMemo(() => {
    const m = {}
    for (const s of subs) for (const k of splitReasons(s.reason)) { (m[s.type] ||= {}); m[s.type][k] = (m[s.type][k] || 0) + 1 }
    return m
  }, [run.id])
  const topPairs = (list) => {
    const c = {}
    for (const s of list) { const k = `${s.orig} → ${s.product}`; c[k] = (c[k] || 0) + 1 }
    return Object.entries(c).sort((a, b) => b[1] - a[1]).slice(0, 2)
  }
  const reasonCount = (list) => {
    const c = {}
    for (const s of list) for (const k of splitReasons(s.reason)) c[k] = (c[k] || 0) + 1
    return Object.entries(c).sort((a, b) => b[1] - a[1])
  }
  const downloadCsv = () => {
    const head = ['어르신', '유형', '식사형태', '일차', '끼니', '칸', '기존 메뉴', '대체 제품', '업체', '조리법', '1인분(g)', '사유', '해결된 문제',
      ...['열량', '단백질', '당류', '나트륨'].flatMap((x) => [`${x}_대체전`, `${x}_대체후`, `${x}_배식후`])]
    const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const lines = shown.map((s) => [s.display_name, s.type, s.texture, s.day, s.meal, s.slot, s.orig, s.product, s.maker, s.cook, s.grams,
      s.reason, (s.resolved || []).map((k) => RESOLVED_LABEL[k] || k).join(' / '),
      ...['energy', 'protein', 'sugar', 'sodium'].flatMap((k) => [s.nut?.meal_before?.[k], s.nut?.meal_after?.[k], s.nut?.served?.[k]])].map(esc).join(','))
    const blob = new Blob(['\ufeff' + [head.map(esc).join(','), ...lines].join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob); a.download = `대체찬_요약_${(run.created_at || '').slice(0, 10)}.csv`; a.click()
    setTimeout(() => URL.revokeObjectURL(a.href), 1000)
  }
  const nRes = withSubs.length
  const top = reasonCount(shown)[0]

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="대체찬" value={shown.length} unit="건" sub="28일 · 선택한 조건" />
        <Stat label="대체 받은 어르신" value={nRes} unit={`/ ${rows.length}명`} sub={`대체 없음 ${without.length}명`} />
        <Stat label="1인 평균" value={nRes ? (shown.length / nRes).toFixed(1) : '–'} unit="건" sub={nRes ? `하루 ${(shown.length / nRes / 28).toFixed(2)}건` : ''} />
        <Stat label="가장 많은 사유" value={top ? top[0] : '–'} sub={top ? `${top[1]}건` : ''} />
      </div>

      <Section title="유형별 대체 사유"
        right={<span className="text-[11px] text-muted">한 대체에 사유가 여러 개면 각각 셉니다</span>}>
        <div className="overflow-x-auto">
          <table className="w-full text-xs tabular-nums" style={{ minWidth: 640 }}>
            <thead><tr className="text-muted border-b border-navy-100">
              <th className="text-left py-1.5 pr-2">유형</th>
              {allReasons.map((k) => <th key={k} className="text-right py-1.5 px-1.5 whitespace-nowrap">{k}</th>)}
            </tr></thead>
            <tbody>
              {Object.keys(matrix).sort().map((t) => (
                <tr key={t} className="border-b border-navy-50">
                  <td className="py-1.5 pr-2 font-semibold text-navy-900 whitespace-nowrap">{t}</td>
                  {allReasons.map((k) => <td key={k} className={`text-right py-1.5 px-1.5 ${matrix[t][k] ? 'text-navy-900' : 'text-slate-300'}`}>{matrix[t][k] || '·'}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section title={`어르신별 대체 내역 (${nRes}명 · ${shown.length}건)`}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <input id="subsum-q" className="form-input !py-1.5 !w-32" placeholder="이름 검색" value={q} onChange={(e) => setQ(e.target.value)} />
            <select id="subsum-type" className="form-select !py-1.5 !w-auto" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="all">모든 유형</option>
              {types.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            <select id="subsum-reason" className="form-select !py-1.5 !w-auto" value={reason} onChange={(e) => setReason(e.target.value)}>
              <option value="all">모든 사유</option>
              {allReasons.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <button className="btn-secondary !py-1.5 text-xs" onClick={downloadCsv} disabled={!shown.length}>엑셀(CSV) 내려받기</button>
          </div>
        }>
        {!withSubs.length && <p className="text-sm text-muted py-4 text-center">조건에 맞는 대체찬이 없습니다.</p>}
        <div className="space-y-2">
          {withSubs.map((r) => {
            const isOpen = !!open[r.elderly_id]
            return (
              <div key={r.elderly_id} className="rounded-xl ring-1 ring-navy-100 bg-white">
                <button className="w-full text-left px-3 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-1"
                  onClick={() => setOpen((o) => ({ ...o, [r.elderly_id]: !o[r.elderly_id] }))}>
                  <span className="text-navy-700 text-xs w-3">{isOpen ? '▾' : '▸'}</span>
                  <span className="font-bold text-navy-900 whitespace-nowrap">{r.display_name}</span>
                  <span className="badge bg-navy-50 text-navy-700">{r.type}</span>
                  <span className="text-xs text-muted whitespace-nowrap">{r.texture}</span>
                  <span className="text-xs font-semibold text-emerald-800 whitespace-nowrap">대체 {r.list.length}건</span>
                  <span className="flex flex-wrap gap-1">
                    {reasonCount(r.list).slice(0, 3).map(([k, v]) => <span key={k} className="badge bg-amber-50 text-amber-800">{k} {v}</span>)}
                  </span>
                  <span className="min-w-0 flex-1 text-xs text-muted truncate">
                    {topPairs(r.list).map(([k, v]) => `${k}${v > 1 ? ` ×${v}` : ''}`).join(' · ')}
                  </span>
                </button>
                {isOpen && (
                  <div className="px-3 pb-3 overflow-x-auto">
                    <table className="w-full text-xs" style={{ minWidth: 980 }}>
                      <thead><tr className="text-muted border-b border-navy-100">
                        {['일차', '끼니', '칸', '기존 메뉴', '', '대체 제품', '조리법', '사유', '해결된 문제', '영양 변화 (끼니)'].map((h, i) =>
                          <th key={i} className="text-left py-1.5 pr-2 font-semibold">{h}</th>)}
                      </tr></thead>
                      <tbody>
                        {r.list.slice().sort((a, b) => dayNo(a.day) - dayNo(b.day) || MEALS.indexOf(a.meal) - MEALS.indexOf(b.meal)).map((s, i) => {
                          const nk = `${r.elderly_id}|${s.day}|${s.meal}|${s.slot}`
                          const nOpen = !!nutOpen[nk]
                          return (<Fragment key={i}>
                          <tr className="border-b border-navy-50 last:border-0 cursor-pointer hover:bg-navy-50/40"
                            onClick={() => setNutOpen((o) => ({ ...o, [nk]: !o[nk] }))} title="눌러서 대체 전후 영양성분 보기">
                            <td className="py-1.5 pr-2 whitespace-nowrap">{s.day}</td>
                            <td className="py-1.5 pr-2 whitespace-nowrap">{s.meal}</td>
                            <td className="py-1.5 pr-2 whitespace-nowrap">{s.slot}</td>
                            <td className="py-1.5 pr-2 text-muted">{s.orig}</td>
                            <td className="py-1.5 pr-2 text-muted">→</td>
                            <td className="py-1.5 pr-2 font-semibold text-emerald-800">{s.product}<span className="block font-normal text-[11px] text-muted">{s.maker}{s.grams ? ` · ${s.grams}g` : ''}</span></td>
                            <td className="py-1.5 pr-2 whitespace-nowrap">{s.cook}</td>
                            <td className="py-1.5 pr-2">{splitReasons(s.reason).map((k) => <span key={k} className="badge bg-amber-50 text-amber-800 mr-1 mb-0.5">{k}</span>)}</td>
                            <td className="py-1.5 pr-2 text-emerald-700">{(s.resolved || []).map((k) => RESOLVED_LABEL[k] || k).join(' · ') || '–'}</td>
                            <td className="py-1.5 pr-2 whitespace-nowrap tabular-nums">
                              <span className="text-navy-700 mr-1">{nOpen ? '▾' : '▸'}</span>
                              {nutChanges(s).join(' · ') || <span className="text-muted">영양 보기</span>}
                            </td>
                          </tr>
                          {nOpen && <tr className="bg-navy-50/30"><td colSpan={10} className="px-2"><NutCompare s={s} lim={r.sub_limits} /></td></tr>}
                          </Fragment>)
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        {without.length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-navy-700 font-semibold">대체 없이 일반식 그대로 드시는 어르신 {without.length}명</summary>
            <p className="mt-1.5 text-muted leading-5">{without.map((r) => `${r.display_name}(${r.type})`).join(' · ')}</p>
          </details>
        )}
        <p className="mt-2 text-[11px] text-muted">사유 = 대체 전 그 끼니가 개인 기준을 벗어난 항목 · 해결된 문제 = 대체 후 사라진 항목 (사유를 하나도 없애지 못하는 교체는 하지 않고 배식량 조정에 맡깁니다. 남은 사유는 배식량으로 맞춥니다). 같은 어르신에게 같은 제품은 14일 안에 다시 쓰지 않으며, 어르신 1명은 한 끼에 최대 2칸, 시설 전체로는 한 끼에 대체 제품 최대 2종까지 씁니다.</p>
      </Section>
    </div>
  )
}

/* ─────────────────────────── ④ 재고·선호도·설정 ─────────────────────────── */

function SettingsTab({ onChanged }) {
  return (
    <div className="space-y-4">
      <InventoryEditor onChanged={onChanged} />
      <PreferencePanel onChanged={onChanged} />
      <ResidentSettings />
    </div>
  )
}

function InventoryEditor({ onChanged }) {
  const [rows, setRows] = useState(null)
  const [start, setStart] = useState('')
  const [paste, setPaste] = useState('')
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api.get('/care/diet/inventory').then((r) => {
      setRows((r.data.items || []).map((x) => ({ ...x })))
      setStart(r.data.start_date || new Date().toISOString().slice(0, 10))
    }).catch((e) => setMsg(errMsg(e)))
  }, [])

  const upd = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const addPaste = () => {
    // 엑셀에서 복사: 식재료명 \t 재고량(g) \t 유통기한
    const add = paste.split('\n').map((l) => l.split('\t')).filter((c) => c[0]?.trim())
      .map((c) => ({ 식재료명: c[0].trim(), '재고량(g)': Number(String(c[1] || '').replace(/[^\d.]/g, '')) || 0, 유통기한: (c[2] || '').trim(), 비고: (c[3] || '').trim() }))
    setRows([...(rows || []), ...add]); setPaste('')
  }
  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const r = await api.put('/care/diet/inventory', { items: rows, start_date: start || null })
      setMsg(`저장했습니다 (${r.data.count}품목).`); onChanged?.()
    } catch (e) { setMsg(errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <Section title="재고"
      right={<>
        <label className="text-xs text-muted">식단 1일차</label>
        <input type="date" className="form-input !py-1.5 !w-auto" value={start} onChange={(e) => setStart(e.target.value)} />
        <button className="btn-secondary" disabled={!start} title="재고 리포트의 추정 재고(식단 1일차 아침 기준)로 표를 채웁니다"
          onClick={async () => {
            try {
              const r = await api.get('/care/diet/stock/snapshot', { params: { date: start }, timeout: 60000 })
              if (!r.data.items.length) { setMsg('추적 중인 재고가 없습니다. 재고 리포트 탭에서 실사를 먼저 입력하세요.'); return }
              setRows(r.data.items); setMsg(`${start} 아침 추정 재고 ${r.data.items.length}건을 불러왔습니다. 저장해야 반영됩니다.`)
            } catch (e) { setMsg(errMsg(e)) }
          }}>추적 재고 불러오기</button>
        <button className="btn-primary" onClick={save} disabled={saving || !rows}>{saving ? '저장 중…' : '재고 저장'}</button>
      </>}>
      <p className="mb-3 text-xs text-muted leading-5">
        식재료명은 레시피 재료명과 같게 씁니다(예: 두부, 시금치, 돼지고기(앞다리)). 유통기한이 가까운 재고일수록 일반식에서 먼저 쓰고,
        남은 재고는 죽식 어르신 영양죽에 씁니다.
      </p>
      {!rows ? <p className="text-sm text-muted">불러오는 중…</p> : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[600px]">
              <thead>
                <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                  <th className="py-2 pr-2">식재료명</th><th className="py-2 pr-2">재고량(g)</th><th className="py-2 pr-2">유통기한</th><th className="py-2 pr-2">비고</th><th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i} className="border-b border-navy-50">
                    <td className="py-1 pr-2"><input className="form-input !py-1.5" value={r.식재료명 || ''} onChange={(e) => upd(i, '식재료명', e.target.value)} /></td>
                    <td className="py-1 pr-2"><input className="form-input !py-1.5 text-right" type="number" value={r['재고량(g)'] ?? ''} onChange={(e) => upd(i, '재고량(g)', e.target.value)} /></td>
                    <td className="py-1 pr-2"><input className="form-input !py-1.5" type="date" value={r.유통기한 || ''} onChange={(e) => upd(i, '유통기한', e.target.value)} /></td>
                    <td className="py-1 pr-2"><input className="form-input !py-1.5" value={r.비고 || ''} onChange={(e) => upd(i, '비고', e.target.value)} /></td>
                    <td className="py-1"><button className="btn-ghost text-xs" onClick={() => setRows(rows.filter((_, j) => j !== i))}>삭제</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-3 flex flex-wrap items-start gap-2">
            <button className="btn-secondary text-xs" onClick={() => setRows([...rows, { 식재료명: '', '재고량(g)': '', 유통기한: '', 비고: '' }])}>+ 행 추가</button>
            <textarea className="form-input !py-1.5 text-xs flex-1 min-w-[240px]" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)}
              placeholder="엑셀에서 '식재료명 · 재고량(g) · 유통기한' 열을 복사해 붙여넣기" />
            <button className="btn-secondary text-xs" disabled={!paste.trim()} onClick={addPaste}>붙여넣은 행 추가</button>
          </div>
        </>
      )}
      {msg && <p className="mt-2 text-xs text-navy-700">{msg}</p>}
    </Section>
  )
}

function PreferencePanel({ onChanged }) {
  const [pref, setPref] = useState(undefined)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const load = () => api.get('/care/diet/preference').then((r) => setPref(r.data)).catch((e) => setMsg(errMsg(e)))
  useEffect(() => { load() }, [])
  const refresh = async () => {
    setBusy(true); setMsg('')
    try { await api.post('/care/diet/preference/refresh', {}, { timeout: 120000 }); await load(); onChanged?.() } catch (e) { setMsg(errMsg(e)) } finally { setBusy(false) }
  }
  const rep = pref?.report
  const served = rep?.served || []
  const effects = rep?.effects || []

  return (
    <Section title="시설 선호도 (잔반 기록)"
      right={<button className="btn-primary" disabled={busy} onClick={refresh}>{busy ? '계산 중…' : '잔반 기록으로 다시 계산'}</button>}>
      <p className="mb-3 text-xs text-muted leading-5">
        영양 조사의 끼니별 잔반(목측)으로 메뉴마다 시설 평균 섭취율을 구하고, 조리법·주재료·양념 같은 메뉴 속성으로 처음 나오는 메뉴와
        고령친화식품의 선호까지 예측합니다. 점수는 다음 식단 설계의 조화 목표(f4, 한 끼 수용성)와 대체 제품 선택에 쓰입니다.
      </p>
      {msg && <p className="mb-2 text-xs text-rose-700">{msg}</p>}
      {pref === undefined ? <p className="text-sm text-muted">불러오는 중…</p> : !rep ? (
        <p className="text-sm text-muted">아직 계산하지 않았습니다.</p>
      ) : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Stat label="잔반 기록" value={rep.n_records} unit="건" sub={rep.period?.join(' ~ ')} />
            <Stat label="관측 메뉴" value={rep.n_menus_observed} unit="개" sub={`${rep.n_residents}명 기록`} />
            <Stat label="시설 평균 섭취율" value={Math.round(rep.facility_mean * 100)} unit="%" />
            <Stat label="갱신" value={fmtDate(pref.updated_at)} />
          </div>
          <div className="grid md:grid-cols-3 gap-4">
            <div>
              <p className="text-xs font-bold text-muted mb-1">덜 드시는 메뉴</p>
              {served.slice(0, 10).map((x) => <div key={x.음식명} className="flex justify-between text-xs py-0.5"><span>{x.음식명}</span><span className="tabular-nums text-rose-600">{Math.round(x.관측섭취율 * 100)}%</span></div>)}
            </div>
            <div>
              <p className="text-xs font-bold text-muted mb-1">잘 드시는 메뉴</p>
              {served.slice(-10).reverse().map((x) => <div key={x.음식명} className="flex justify-between text-xs py-0.5"><span>{x.음식명}</span><span className="tabular-nums text-emerald-700">{Math.round(x.관측섭취율 * 100)}%</span></div>)}
            </div>
            <div>
              <p className="text-xs font-bold text-muted mb-1">고령친화식품 예측 선호</p>
              {(rep.products || []).map((x) => <div key={x.제품} className="flex justify-between text-xs py-0.5"><span>{x.제품}</span><span className="tabular-nums">{Math.round(x.예측점수 * 100)}</span></div>)}
            </div>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer text-navy-700 font-semibold">속성 효과 · 예측 검증</summary>
            <div className="mt-3 grid md:grid-cols-2 gap-4">
              <div>
                {[...effects.slice(0, 6), ...effects.slice(-6)].map((x) => (
                  <div key={x.속성} className="flex justify-between text-xs py-0.5">
                    <span>{x.속성}</span><span className={`tabular-nums ${x['효과(섭취율)'] < 0 ? 'text-rose-600' : 'text-emerald-700'}`}>{x['효과(섭취율)'] > 0 ? '+' : ''}{x['효과(섭취율)']}</span>
                  </div>
                ))}
              </div>
              <Table rows={rep.cv} minW={300} cols={[{ key: '방식', label: '처음 나오는 메뉴 예측' }, { key: 'MAE', label: '평균 오차', right: true }, { key: '상관계수', label: '상관', right: true }]} />
            </div>
          </details>
        </div>
      )}
    </Section>
  )
}

function ResidentSettings() {
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState('')
  const load = () => api.get('/care/diet/residents', { timeout: 60000 }).then((r) => setData(r.data)).catch((e) => setMsg(errMsg(e)))
  useEffect(() => { load() }, [])
  const toggle = async (r) => {
    try {
      await api.put(`/care/diet/residents/${r.elderly_id}/settings`, { no_spicy: !r.no_spicy, note: r.note || null })
      setData({ ...data, residents: data.residents.map((x) => (x.elderly_id === r.elderly_id ? { ...x, no_spicy: !r.no_spicy } : x)) })
    } catch (e) { setMsg(errMsg(e)) }
  }
  return (
    <Section title="어르신 식단 설정">
      <p className="mb-3 text-xs text-muted">질환·식사형태·목표 열량은 진단 평가에서 가져옵니다. 매운 음식을 못 드시는 어르신은 김치 칸이 백김치로 나갑니다.</p>
      {msg && <p className="mb-2 text-xs text-rose-700">{msg}</p>}
      {!data ? <p className="text-sm text-muted">불러오는 중…</p> : (
        <>
          <Table rows={data.residents} minW={720} rowKey={(r) => r.elderly_id} cols={[
            { key: 'display_name', label: '어르신', cls: 'font-semibold text-navy-900' },
            { key: 'type', label: '질환 유형' },
            { key: 'texture', label: '식사형태' },
            { key: 'target_energy', label: '목표 열량(끼)', right: true, render: (r) => Math.round(r.target_energy) },
            { key: 'sodium_max', label: '나트륨 상한(끼)', right: true },
            { key: 'no_spicy', label: '매운 음식', render: (r) => (
              <button onClick={() => toggle(r)} className={`badge ${r.no_spicy ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'}`}>
                {r.no_spicy ? '불가 · 백김치' : '가능'}
              </button>) },
          ]} />
          {data.skipped?.length > 0 && (
            <p className="mt-3 text-xs text-muted">평가 기록이 없어 제외된 어르신 {data.skipped.length}명: {data.skipped.map((x) => x.display_name).join(', ')}</p>
          )}
        </>
      )}
    </Section>
  )
}

/* ─────────────────────────── 재고 리포트 (재고 추적) ─────────────────────────── */

const todayKst = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10)
const STATUS_CLS = {
  '유통기한 지남': 'bg-rose-100 text-rose-700', '유통기한 임박': 'bg-amber-100 text-amber-800',
  '부족 예상': 'bg-orange-100 text-orange-800', '남을 위험': 'bg-violet-100 text-violet-700', '실사 필요': 'bg-slate-100 text-slate-600',
}
const KIND_CLS = { 입고: 'bg-emerald-50 text-emerald-700', 실사: 'bg-navy-50 text-navy-700', 폐기: 'bg-rose-50 text-rose-700' }

function StockTab() {
  const [date, setDate] = useState(todayKst())
  const [rep, setRep] = useState(null)
  const [events, setEvents] = useState(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState('all')
  const [open, setOpen] = useState(null)

  const load = () => {
    setErr('')
    api.get('/care/diet/stock/report', { params: { date }, timeout: 60000 }).then((r) => setRep(r.data)).catch((e) => setErr(errMsg(e)))
    api.get('/care/diet/stock/events', { params: { limit: 300 } }).then((r) => setEvents(r.data)).catch(() => {})
  }
  useEffect(() => { load() }, [date])

  const [recv, setRecv] = useState('')
  const planRun = rep?.plan?.run_id || rep?.next_plan?.run_id
  const receive = async () => {
    setRecv('반영 중…'); setErr('')
    try {
      const r = await api.post(`/care/diet/runs/${planRun}/receive-plan`, {}, { timeout: 60000 })
      setRecv(`주간 발주량 ${r.data.received}건을 입고로 기록했습니다.`); load()
    } catch (e) { setRecv(''); setErr(errMsg(e)) }
  }
  const del = async (id) => {
    try { await api.delete(`/care/diet/stock/events/${id}`); load() } catch (e) { setErr(errMsg(e)) }
  }
  const s = rep?.summary || {}
  const items = (rep?.items || []).filter((x) => filter === 'all' || x.상태.includes(filter))
  const isToday = date === todayKst()

  return (
    <div className="space-y-4">
      {err && <p className="text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}
      <Section title={`${isToday ? '오늘 아침' : date} 재고 리포트`}
        right={<>
          <input type="date" className="form-input !py-1.5 !w-auto" value={date} onChange={(e) => setDate(e.target.value)} />
          {!isToday && <button className="btn-ghost text-xs" onClick={() => setDate(todayKst())}>오늘</button>}
        </>}>
        {!rep ? <p className="text-sm text-muted">불러오는 중…</p> : (
          <>
            <p className="mb-3 text-xs text-muted leading-5">
              {rep.plan
                ? <>승인 식단 <b className="text-navy-900">{rep.plan.day}일차</b> ({rep.plan.start_date} ~ {rep.plan.end_date}) 기준. </>
                : rep.next_plan
                  ? <span className="text-navy-700">승인 식단은 <b>{rep.next_plan.start_date}</b>부터 시작합니다{rep.next_plan.days_until === 1 ? '(내일)' : ` (${rep.next_plan.days_until}일 뒤)`}. 오늘 사용량은 없고, 앞으로 7일 사용 예정량은 반영됩니다. </span>
                  : <span className="text-amber-700">이 날짜를 포함하는 승인 식단이 없어 예상 사용량이 0입니다. 식단표 탭에서 시작일을 정해 승인하세요. </span>}
              추정 재고 = 마지막 실사 + 입고 − 승인 식단 예상 사용량 − 폐기 (유통기한 빠른 것부터 사용). 실제와 차이가 나면 실사로 맞춰 주세요.
            </p>
            {planRun && (
              <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-navy-50/60 px-3 py-2 text-xs text-navy-700">
                <span>승인 식단의 <b>주간 발주량</b>을 각 주 1일차 전날 <b>입고</b>로 기록하면, 실사 없이도 매일 남은 양이 계산됩니다. 유통기한은 식재료 종류별 추정값(잎채소 3일 · 고기 3일 · 두부 4일 · 달걀 21일 · 양파 30일 …)으로 넣습니다. (다시 누르면 자동입고를 새로 계산)</span>
                <button className="btn-secondary text-xs ml-auto" onClick={receive} disabled={recv === '반영 중…'}>발주량을 입고로 반영</button>
                {recv && <span className="w-full text-emerald-700">{recv}</span>}
              </div>
            )}
            <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
              <Stat label="추적 품목" value={s.품목} unit="개" sub={`${s['추정재고(kg)'] ?? 0}kg`} />
              <Stat label="유통기한 지남" value={s.유통기한지남} unit="개" tone={s.유통기한지남 ? 'bg-rose-50' : undefined} sub="폐기 확인" />
              <Stat label="유통기한 임박" value={s.유통기한임박} unit="개" tone={s.유통기한임박 ? 'bg-amber-50' : undefined} sub="D-3 이내" />
              <Stat label="부족 예상" value={s.부족예상} unit="개" tone={s.부족예상 ? 'bg-orange-50' : undefined} sub="7일 안에 소진" />
              <Stat label="남을 위험" value={s.남을위험} unit="개" sub="기한 내 다 못 씀" />
              <Stat label="실사 필요" value={s.실사필요} unit="개" sub="7일 넘게 미확인" />
            </div>
            {rep.today_menu?.length > 0 && (
              <div className="mt-4 grid md:grid-cols-3 gap-2">
                {rep.today_menu.map((m) => (
                  <div key={m.끼니} className="rounded-xl bg-navy-50/60 px-3 py-2 text-xs">
                    <b className="text-navy-900">{m.끼니}</b>
                    <span className="ml-2 text-navy-700">{[m.밥, m.국, m.주찬, m.부찬1, m.부찬2, m.김치].filter((x) => x && !String(x).startsWith('-')).join(' · ')}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </Section>

      {rep?.expiring?.length > 0 && (
        <Section title="유통기한 확인">
          <Table rows={rep.expiring} minW={520} cols={[
            { key: '식재료명', label: '식재료', cls: 'font-semibold text-navy-900' },
            { key: '양(g)', label: '양', right: true, render: (r) => kg(r['양(g)']) },
            { key: '유통기한', label: '유통기한' },
            { key: 'D', label: '남은 날', right: true, render: (r) => <span className={r.D < 0 ? 'text-rose-600 font-semibold' : 'text-amber-700 font-semibold'}>{r.D < 0 ? `${-r.D}일 지남` : r.D === 0 ? '오늘까지' : `D-${r.D}`}</span> },
            { key: '기한내사용(g)', label: '기한 안 사용 예정', right: true, render: (r) => kg(r['기한내사용(g)']) },
            { key: '남을양(g)', label: '남을 양', right: true, render: (r) => (r['남을양(g)'] > Math.max(50, 0.05 * r['양(g)'])
              ? <span className="text-rose-600 font-semibold">{kg(r['남을양(g)'])} → 다른 메뉴·영양죽에 먼저 사용</span>
              : <span className="text-emerald-700">기한 안에 사용</span>) },
          ]} />
          <p className="mt-2 text-[11px] text-muted">유통기한이 '추정'인 품목은 입고 때 실제 날짜로 고쳐 주면 더 정확합니다(기록 목록의 비고에 추정 표시).</p>
        </Section>
      )}

      <Section title="재고 현황"
        right={<div className="flex flex-wrap gap-1">
          {['all', '유통기한 지남', '유통기한 임박', '부족 예상', '남을 위험', '실사 필요'].map((k) => (
            <button key={k} onClick={() => setFilter(k)} className={`px-2.5 py-1 rounded-full text-[11px] font-semibold ${filter === k ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>{k === 'all' ? '전체' : k}</button>
          ))}
        </div>}>
        {rep && !rep.items?.length ? (
          <div className="py-4 text-center text-sm text-muted leading-6">
            <p>아직 재고 기록이 없어 추적할 식재료가 없습니다.</p>
            <p>아래 <b className="text-navy-900">재고 입력</b>에서 <b className="text-navy-900">실사</b>를 골라 지금 창고에 있는 식재료와 양(g)·유통기한을 넣으면,
              승인 식단의 사용량만큼 매일 자동으로 줄어듭니다. 아래 '재고 등록 안 된 식재료' 목록을 참고하세요.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[980px]">
              <thead>
                <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                  <th className="py-2 pr-2">식재료</th><th className="py-2 pr-2 text-right">추정 재고</th><th className="py-2 pr-2 text-right">오늘 사용</th>
                  <th className="py-2 pr-2 text-right">7일 사용</th><th className="py-2 pr-2 text-right">남는 일수</th><th className="py-2 pr-2">소진 예상</th>
                  <th className="py-2 pr-2">가장 빠른 유통기한</th><th className="py-2 pr-2">마지막 실사</th><th className="py-2">상태</th>
                </tr>
              </thead>
              <tbody>
                {items.map((x) => (
                  <Fragment key={x.식재료명}>
                    <tr className="border-b border-navy-50 cursor-pointer hover:bg-navy-50/40" onClick={() => setOpen(open === x.식재료명 ? null : x.식재료명)}>
                      <td className="py-1.5 pr-2 font-semibold text-navy-900">{x.식재료명}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums font-semibold">{kg(x['추정재고(g)'])}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{x['오늘사용(g)'] ? kg(x['오늘사용(g)']) : '–'}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{x['7일사용(g)'] ? kg(x['7일사용(g)']) : '–'}</td>
                      <td className="py-1.5 pr-2 text-right tabular-nums">{x.남는일수 != null ? `${x.남는일수}일` : '–'}</td>
                      <td className="py-1.5 pr-2">{x.소진예상 ? <span className="text-orange-700 font-semibold">{x.소진예상} (부족 {kg(x['부족량(g)'])})</span> : '–'}</td>
                      <td className="py-1.5 pr-2 tabular-nums">{x.가장빠른유통기한 ? `${x.가장빠른유통기한.slice(5)} (${x.D < 0 ? `${-x.D}일 지남` : `D-${x.D}`})` : '–'}</td>
                      <td className="py-1.5 pr-2 text-xs text-muted">{x.마지막실사 ? `${x.마지막실사.slice(5)} · ${x.실사경과일}일 전` : '없음'}</td>
                      <td className="py-1.5">{x.상태.map((t) => <span key={t} className={`badge mr-1 ${STATUS_CLS[t]}`}>{t}</span>)}</td>
                    </tr>
                    {open === x.식재료명 && (
                      <tr className="bg-navy-50/30">
                        <td colSpan={9} className="px-3 py-2 text-xs text-navy-700">
                          {x.로트.length ? x.로트.map((l, i) => (
                            <span key={i} className="mr-4">{kg(l['양(g)'])} · 유통기한 {l.유통기한 || '미기재'} · {l.입고} 입고/확인</span>
                          )) : '남은 재고 없음'}
                          {x['남을위험(g)'] > 0 && <span className="ml-2 text-violet-700">· 유통기한까지 약 {kg(x['남을위험(g)'])} 남을 수 있음 → 다른 메뉴·영양죽에 먼저 사용</span>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rep?.untracked?.length > 0 && (
          <details className="mt-3 text-xs">
            <summary className="cursor-pointer text-navy-700 font-semibold">재고 등록 안 된 식재료 중 7일 사용 많은 것 ({rep.untracked.length})</summary>
            <p className="mt-2 text-muted leading-6">{rep.untracked.map((u) => `${u.식재료명} ${kg(u['7일사용(g)'])}`).join(' · ')}</p>
          </details>
        )}
      </Section>

      <StockEntry onSaved={load} items={rep?.items || []} />

      <Section title="입고·실사·폐기 기록">
        <Table rows={events} minW={720} empty="기록이 없습니다." rowKey={(r) => r.id} cols={[
          { key: 'event_date', label: '날짜' },
          { key: 'kind', label: '종류', render: (r) => <span className={`badge ${KIND_CLS[r.kind]}`}>{r.kind}</span> },
          { key: 'ingredient', label: '식재료', cls: 'font-semibold text-navy-900' },
          { key: 'qty_g', label: '양', right: true, render: (r) => kg(Number(r.qty_g)) },
          { key: 'expiry', label: '유통기한' },
          { key: 'note', label: '비고', cls: 'text-xs text-muted' },
          { key: 'id', label: '', render: (r) => <button className="btn-ghost text-xs" onClick={() => del(r.id)}>삭제</button> },
        ]} />
      </Section>
    </div>
  )
}

function StockEntry({ onSaved, items }) {
  const [kind, setKind] = useState('실사')
  const [date, setDate] = useState(todayKst())
  const [rows, setRows] = useState([{ 식재료명: '', 수량: '', 유통기한: '', 비고: '' }])
  const [paste, setPaste] = useState('')
  const [msg, setMsg] = useState('')
  const [saving, setSaving] = useState(false)
  const [autoExp, setAutoExp] = useState(true)
  const upd = (i, k, v) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
  const addPaste = () => {
    const add = paste.split('\n').map((l) => l.split('\t')).filter((c) => c[0]?.trim())
      .map((c) => ({ 식재료명: c[0].trim(), 수량: String(c[1] || '').replace(/[^\d.]/g, ''), 유통기한: (c[2] || '').trim(), 비고: (c[3] || '').trim() }))
    setRows([...rows.filter((r) => r.식재료명), ...add]); setPaste('')
  }
  const fillCurrent = () => setRows(items.map((x) => ({ 식재료명: x.식재료명, 수량: '', 유통기한: '', 비고: `추정 ${Math.round(x['추정재고(g)'])}g` })))
  const save = async () => {
    setSaving(true); setMsg('')
    try {
      const body = { date, kind, auto_expiry: autoExp, items: rows.filter((r) => r.식재료명 && r.수량 !== '').map((r) => ({ ...r, 수량: Number(r.수량), 유통기한: r.유통기한 || null })) }
      const r = await api.post('/care/diet/stock/events', body)
      setMsg(`${kind} ${r.data.count}건을 저장했습니다.`); setRows([{ 식재료명: '', 수량: '', 유통기한: '', 비고: '' }]); onSaved?.()
    } catch (e) { setMsg(errMsg(e)) } finally { setSaving(false) }
  }
  const HELP = {
    실사: '창고에서 실제로 센 양입니다. 그날 아침(배식 전) 기준으로 재고를 이 값으로 맞춥니다. 유통기한까지 적으면 그 기한으로 교체합니다.',
    입고: '들어온 식재료의 양과 유통기한입니다. 기존 재고에 더해지고, 유통기한 빠른 것부터 사용됩니다.',
    폐기: '버린 양입니다. 유통기한 빠른 것부터 뺍니다.',
  }
  return (
    <Section title="재고 입력"
      right={<>
        <div className="flex rounded-xl bg-navy-50 p-1">
          {['실사', '입고', '폐기'].map((k) => (
            <button key={k} onClick={() => setKind(k)} className={`px-3 py-1 rounded-lg text-xs font-semibold ${kind === k ? 'bg-white text-navy-900 shadow-sm' : 'text-muted'}`}>{k}</button>
          ))}
        </div>
        <input type="date" className="form-input !py-1.5 !w-auto" value={date} onChange={(e) => setDate(e.target.value)} />
        <button className="btn-primary" disabled={saving} onClick={save}>{saving ? '저장 중…' : `${kind} 저장`}</button>
      </>}>
      <p className="mb-3 text-xs text-muted leading-5">{HELP[kind]} 식재료명은 레시피 재료명과 같게 씁니다(예: 두부, 양파, 돼지고기(앞다리)). 양은 g 단위입니다.</p>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[600px]">
          <thead>
            <tr className="text-left text-[11px] text-muted border-b border-navy-100">
              <th className="py-2 pr-2">식재료명</th><th className="py-2 pr-2">{kind === '실사' ? '실제 재고(g)' : '양(g)'}</th>
              <th className="py-2 pr-2">유통기한{kind === '폐기' ? ' (선택)' : ''}</th><th className="py-2 pr-2">비고</th><th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-b border-navy-50">
                <td className="py-1 pr-2"><input className="form-input !py-1.5" value={r.식재료명} onChange={(e) => upd(i, '식재료명', e.target.value)} /></td>
                <td className="py-1 pr-2"><input className="form-input !py-1.5 text-right" type="number" value={r.수량} onChange={(e) => upd(i, '수량', e.target.value)} /></td>
                <td className="py-1 pr-2"><input className="form-input !py-1.5" type="date" value={r.유통기한} onChange={(e) => upd(i, '유통기한', e.target.value)} /></td>
                <td className="py-1 pr-2"><input className="form-input !py-1.5" value={r.비고} onChange={(e) => upd(i, '비고', e.target.value)} /></td>
                <td className="py-1"><button className="btn-ghost text-xs" onClick={() => setRows(rows.filter((_, j) => j !== i))}>삭제</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex flex-wrap items-start gap-2">
        <button className="btn-secondary text-xs" onClick={() => setRows([...rows, { 식재료명: '', 수량: '', 유통기한: '', 비고: '' }])}>+ 행 추가</button>
        {kind === '실사' && items.length > 0 && <button className="btn-secondary text-xs" onClick={fillCurrent}>추적 중인 품목 불러오기</button>}
        {kind !== '폐기' && (
          <label className="flex items-center gap-1.5 text-xs text-muted self-center" title="잎채소 3일 · 고기 3일 · 생선 2일 · 두부 4일 · 버섯 5일 · 달걀 21일 · 뿌리채소 14일 · 양파·감자 30일 · 곡류·양념 180일 등">
            <input type="checkbox" checked={autoExp} onChange={(e) => setAutoExp(e.target.checked)} />유통기한 비우면 추정값으로 채우기
          </label>
        )}
        <textarea className="form-input !py-1.5 text-xs flex-1 min-w-[240px]" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)}
          placeholder="엑셀에서 '식재료명 · 양(g) · 유통기한' 열을 복사해 붙여넣기" />
        <button className="btn-secondary text-xs" disabled={!paste.trim()} onClick={addPaste}>붙여넣은 행 추가</button>
      </div>
      {msg && <p className="mt-2 text-xs text-navy-700">{msg}</p>}
    </Section>
  )
}

/* ─────────────────────────── 영역별 에이전트 평가 (Stage 1) ─────────────────────────── */

const SRC_SHORT = {
  KDRI2025: '2025 영양소 섭취기준', ESPEN_GERIATRIC: 'ESPEN 노인영양', ESPEN_DEMENTIA: 'ESPEN 치매영양', IDDSI: 'IDDSI',
  LTC_MEAL_GUIDE: '복지부 급식관리', KSH_HTN_2026: '고혈압학회 2026', KDA_DM_2025: '당뇨병학회 2025', SARCOPENIA_KR: '근감소증 종설', DRUG_FOOD: '약물-식품 규칙', BRAIN_DIET: '뇌건강 식사 근거', MFDS_EASY: '식약처 e약은요', MFDS_MEAL_STD: '식약처 식단형 규격',
}
const AGENT_LABEL = { body: '신체·영양', diabetes: '당뇨', hypertension: '고혈압', cognition: '인지·정서', oral: '구강·연하',
  intake: '섭취·선호', medication: '약물·알레르기', base: '기본 기준', kdri: 'KDRI 공통' }
const FIELD_LABEL = {
  energy_min: ['열량', '≥', 'kcal'], energy_max: ['열량', '≤', 'kcal'], protein_min: ['단백질', '≥', 'g'], protein_max: ['단백질', '≤', 'g'],
  sugar_max: ['당류', '≤', 'g'], fat_min: ['지방', '≥', 'g'], fat_max: ['지방', '≤', 'g'], sat_fat_max: ['포화지방', '≤', 'g'],
  sodium_max: ['나트륨', '≤', 'mg'], potassium_min: ['칼륨', '≥', 'mg'], fiber_min: ['식이섬유', '≥', 'g'],
}
const ACTION_LABEL = { limit: '줄이기', increase: '늘리기', avoid: '피하기', texture: '식사형태', monitor: '관찰', check: '확인 필요', timing: '복약 시간' }

/* [Stage 3] 어르신별 영양 관리 계획 (ADIME) — 요청할 때 작성 */
function CarePlan({ run, eid, setErr, bare = false }) {
  const [plan, setPlan] = useState(run.result?.care_plans?.[eid] || null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setPlan(run.result?.care_plans?.[eid] || null) }, [run.id, eid])
  const make = async () => {
    setBusy(true); setErr('')
    try {
      const r = await api.post(`/care/diet/runs/${run.id}/residents/${eid}/plan`, {}, { timeout: 180000 })   // LLM 작성 — 기본 15초로는 부족
      setPlan(r.data)
      if (run.result) run.result.care_plans = { ...(run.result.care_plans || {}), [eid]: r.data }   // 다른 어르신 보고 돌아와도 유지
    }
    catch (e) { setErr(errMsg(e)) } finally { setBusy(false) }
  }
  return (
    <div className={bare ? '' : 'mb-4 rounded-2xl bg-white ring-1 ring-navy-100 px-4 py-3'}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-bold text-navy-900">AI 영양 관리 계획 <span className="font-normal text-xs text-muted">— 평가 · 영양 진단 · 중재 · 모니터링 (Stage 3)</span></p>
        <button className="btn-secondary !py-1 text-xs" disabled={busy} onClick={make}>{busy ? '작성 중…' : plan ? '다시 작성' : '계획 작성'}</button>
      </div>
      {plan ? (
        <div className="mt-2 grid md:grid-cols-2 gap-3 text-xs">
          <div className="space-y-2">
            <div><p className="font-bold text-muted mb-0.5">A 평가</p><p className="text-navy-900 leading-5">{plan.assessment}</p></div>
            <div><p className="font-bold text-muted mb-0.5">D 영양 진단 (문제 — 원인 — 근거)</p>
              <ul className="list-disc pl-4 space-y-0.5">{(plan.diagnosis || []).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
          </div>
          <div className="space-y-2">
            <div><p className="font-bold text-muted mb-0.5">I 중재</p>
              <ul className="space-y-0.5">{(plan.intervention || []).map((x, i) => <li key={i}><b className="text-navy-900">{x.goal}</b> · {x.action}{x.auto && <span className="badge bg-slate-100 text-slate-600 ml-1" title="배식 결과를 보고 시스템이 붙인 권장">자동</span>}</li>)}</ul></div>
            <div><p className="font-bold text-muted mb-0.5">M 모니터링</p>
              <ul className="list-disc pl-4 space-y-0.5">{(plan.monitoring || []).map((x, i) => <li key={i}>{x}</li>)}</ul></div>
          </div>
          <p className="md:col-span-2 text-navy-800"><b>담당자 요약</b> {plan.staff_summary}</p>
          {(plan.to_confirm || []).length > 0 && <p className="md:col-span-2 text-amber-800"><b>추가 확인 정보</b> · {plan.to_confirm.join(' · ')}</p>}
          {(plan.evidence || []).length > 0 && (
            <div className="md:col-span-2 text-[11px] text-muted"><b className="text-navy-800">근거</b>{' '}
              {plan.evidence.map((e) => <span key={e.id} className="mr-2"><b className="text-navy-800">[{e.id}]</b> {e.short} — {e.조항}</span>)}</div>
          )}
          <p className="md:col-span-2 text-[11px] text-muted">{plan.model} · {plan.latency_sec}초 · {plan.created_at} · 프롬프트 {plan.prompt_version}
            {(plan.warnings || []).length > 0 && <span className="text-amber-700"> · ⚠ {plan.warnings.join(' · ')} — 숫자는 위 평가표로 확인하세요</span>}</p>
        </div>
      ) : <p className="mt-1 text-xs text-muted">이 어르신의 평가 결과와 시스템이 한 조치(대체찬·배식량·식사형태)를 바탕으로 영양 관리 계획을 작성합니다.</p>}
    </div>
  )
}

// 우선순위 2단계 (backend agents/base.py 와 같은 규칙 — 예전 설계 결과에는 level 이 없어서 여기서도 판정)
const SAFETY_CODES = new Set(['allergy', 'aspiration_risk', 'texture_mismatch', 'chewing', 'hypoglycemia_risk'])
const issueLevel = (i) => i.level || (SAFETY_CODES.has(i.code) || i.agent === 'medication' ? 1 : 2)

/* Stage 1 AI 영역 전문가 판단 (근거 검색 RAG) — 요약 · 우려 · 추가 확인 · 근거 문단 */
function AgentLlm({ g }) {
  const l = g.llm
  if (!l) return null
  if (l.mode !== 'llm') return l.note ? <p className="mt-1 text-[11px] text-muted">{l.note}</p> : null
  return (
    <div className="mt-1.5 space-y-1 border-t border-navy-100 pt-1.5">
      {l.summary && <p className="text-violet-900 leading-5"><span className="badge bg-violet-50 text-violet-700 mr-1">AI</span>{l.summary}</p>}
      {(l.concerns || []).map((x, k) => <p key={`c${k}`} className="text-amber-800 leading-5">⚠ {x}</p>)}
      {(l.missing || []).length > 0 && <p className="text-muted leading-5">추가 확인: {l.missing.join(' · ')}</p>}
      {(g.evidence || []).length > 0 && (
        <details>
          <summary className="cursor-pointer text-[11px] text-navy-700">근거 문단 {g.evidence.length}개</summary>
          <ul className="mt-1 space-y-0.5 text-[11px] text-muted">
            {g.evidence.map((e) => (
              <li key={e.tag}><b className="text-navy-800">{e.tag}</b> {SRC_SHORT[e.source_id] || e.short} — {e.section}{e.page ? ` · p.${e.page}` : ''}{e.kind === 'search' ? ' (검색)' : ''}</li>
            ))}
          </ul>
        </details>
      )}
      {(l.warnings || []).length > 0 && <p className="text-[11px] text-amber-700" title={l.warnings.join('\n')}>검증 경고 {l.warnings.length}건</p>}
    </div>
  )
}

const agentName = (g) => (String(g || '').startsWith('specialist:') ? '질환 전문가' : AGENT_LABEL[g] || g)

/* [3단계] 종합·안전성 검증 — 안전성 → 우선순위(파레토) → 지침 충돌 조정 → 약물·질환 강제 제약 (agents/synthesis.py) */
function SynthesisBox({ s }) {
  if (!s) return null
  return (
    <div className="rounded-xl bg-teal-50/60 ring-1 ring-teal-100 px-3 py-2 text-xs space-y-1.5">
      <p className="font-bold text-teal-900">종합·안전성 검증 <span className="font-normal text-teal-700">(3단계 · 고정 순서{s.specialists_on ? ' · 충돌별 질환 전문가 AI' : ' · 규칙'})</span></p>
      <ol className="space-y-1">
        {(s.steps || []).map((st) => (
          <li key={st.step}>
            <b className="text-navy-900">{st.step}. {st.name}</b>
            <ul className="pl-4 list-disc text-navy-800 leading-5">{st.items.map((t, k) => <li key={k}>{t}</li>)}</ul>
          </li>
        ))}
      </ol>
      {(s.conflicts || []).filter((c) => c.specialist).map((c) => {
        const sp = c.specialist
        return (
          <div key={c.id} className="border-t border-teal-100 pt-1">
            <p><span className="badge bg-white text-teal-700">{sp.specialist || '전문가'}</span> {c.title}
              {sp.mode !== 'llm' && <span className="text-muted"> — {sp.note}</span>}</p>
            {sp.mode === 'llm' && <>
              <p className="text-violet-900 leading-5">{sp.resolution}</p>
              {(sp.adjustments || []).map((x, k) => <p key={k}>기준 {x.label} {x.before} → <b>{x.after}</b>{x.clamped ? ' (허용 범위로 맞춤)' : ''} — {x.reason}</p>)}
              {(sp.rescore || []).map((x, k) => <p key={`r${k}`}>우선순위 {x.title}: S {x.before.priority} → <b>{x.after.priority}</b> — {x.reason}</p>)}
              {(sp.evidence || []).length > 0 && (
                <details><summary className="cursor-pointer text-[11px] text-navy-700">근거 문단 {sp.evidence.length}개</summary>
                  <ul className="mt-1 space-y-0.5 text-[11px] text-muted">{sp.evidence.map((e) => <li key={e.tag}><b className="text-navy-800">{e.tag}</b> {SRC_SHORT[e.source_id] || e.short} — {e.section}{e.kind === 'search' ? ' (검색)' : ''}</li>)}</ul>
                </details>
              )}
              {(sp.warnings || []).length > 0 && <p className="text-[11px] text-amber-700" title={sp.warnings.join('\n')}>검증 경고 {sp.warnings.length}건</p>}
            </>}
          </div>
        )
      })}
      {(s.to_confirm || []).length > 0 && <p className="text-amber-800 leading-5"><b>추가 확인 정보</b> · {s.to_confirm.join(' · ')}</p>}
    </div>
  )
}

function PriorityRow({ i }) {
  const l1 = issueLevel(i) === 1
  const ai = i.scores_rule && Math.abs((i.scores_rule.priority ?? i.priority) - i.priority) > 0.0005
  return (
    <tr className="border-b border-navy-50 last:border-0">
      <td className="py-1 pr-2 w-14 tabular-nums font-bold text-navy-900" title={l1 ? `안전성 — 점수(S ${i.priority.toFixed(2)})와 무관하게 최우선` : i.priority_stage1 != null ? `영역 평가 ${i.priority_stage1} → AI 재평가` : undefined}>
        {l1 ? <span className="badge bg-rose-50 text-rose-700">안전</span> : <>{i.priority.toFixed(2)}{i.priority_stage1 != null && <span className="text-violet-600">*</span>}{ai && <span className="text-sky-600" title={`규칙 S ${i.scores_rule.priority} → AI 영역 전문가 ${i.priority}`}>†</span>}{(i.adjusted_by || []).length > 0 && <span className="text-teal-600" title={`3단계 종합에서 조정: ${i.adjusted_by.join(', ')}${i.scores_before_synthesis ? ` (S ${i.scores_before_synthesis.priority} → ${i.priority})` : ''}`}>‡</span>}</>}
      </td>
      <td className="py-1 pr-2 whitespace-nowrap"><span className="badge bg-white ring-1 ring-navy-100 text-navy-700">{AGENT_LABEL[i.agent] || i.agent}</span></td>
      <td className="py-1 pr-2 font-semibold text-navy-900">{i.pareto_rank > 0 && <span className="badge bg-slate-100 text-slate-600 mr-1" title="파레토 묶음 — 심각도·시급성·개선 가능성 세 가지 모두에서 앞서는 다른 문제가 없으면 1묶음">{i.pareto_rank}묶음</span>}{i.title}
        {i.rationale && <p className="font-normal text-[11px] text-violet-800 leading-4 mt-0.5">{i.rationale}</p>}</td>
      <td className="py-1 pr-2 whitespace-nowrap"><span className={`badge ${i.action === 'avoid' ? 'bg-rose-50 text-rose-700' : i.action === 'check' ? 'bg-amber-50 text-amber-800' : 'bg-slate-100 text-slate-600'}`}>{ACTION_LABEL[i.action] || i.action}</span></td>
      <td className="py-1 pr-2 text-muted">{(i.evidence || []).join(' · ')}</td>
      <td className="py-1 text-muted whitespace-nowrap">{SRC_SHORT[i.source] || i.source}</td>
    </tr>
  )
}

function AgentPanel({ a }) {
  if (!a) return <p className="text-xs text-muted">이 설계에는 영역별 에이전트 평가가 없습니다. 식단 설계를 다시 실행하면 함께 계산됩니다.</p>
  const syn = a.synth || {}
  const all = syn.priorities || []
  const pri1 = all.filter((i) => issueLevel(i) === 1)
  const pareto = all.some((i) => i.pareto_rank != null)
  // 3단계 이후 결과는 백엔드 순서(파레토 묶음 → S) 그대로, 예전 결과는 S 순
  const pri2 = all.filter((i) => issueLevel(i) === 2 && i.priority >= 0.3)
  if (!pareto) pri2.sort((x, y) => y.priority - x.priority)
  const pri = [...pri1, ...pri2]
  const rf = a.refine
  return (
    <div className="space-y-3">
      {rf && rf.mode === 'llm' && (
        <div className="rounded-xl bg-violet-50/70 ring-1 ring-violet-100 px-3 py-2 text-xs space-y-1.5">
          <p className="font-bold text-violet-900">AI 임상 영양사 종합 판단 <span className="font-normal text-violet-700">(Stage 2 · {rf.model}{rf.reused ? ' · 이전 결과 재사용' : ''})</span></p>
          {rf.summary && <p className="text-navy-900">{rf.summary}</p>}
          {(rf.conflicts || []).map((c, k) => (
            <p key={k}><span className="badge bg-white text-violet-700">충돌</span> {(c.agents || []).map((g) => AGENT_LABEL[g] || g).join(' ↔ ')}: {c.description} → <b>{c.resolution}</b></p>
          ))}
          {(rf.adjustments || []).map((x, k) => (
            <p key={k}><span className="badge bg-white text-violet-700">기준 조정</span> {x.label} {x.before} → <b>{x.after}</b>{x.clamped ? ' (허용 범위로 맞춤)' : ''} — {x.reason}</p>
          ))}
          {rf.target_energy && <p><span className="badge bg-white text-violet-700">목표 열량</span> {rf.target_energy.before} → <b>{rf.target_energy.after}</b>kcal/끼{rf.target_energy.clamped ? ' (허용 범위로 맞춤)' : ''} — {rf.target_energy.reason}</p>}
          {(rf.energy_rescaled || []).length > 0 && (
            <p><span className="badge bg-white text-violet-700">열량 기준 재계산</span> 바뀐 목표 열량으로 다시 계산: {rf.energy_rescaled.map((x) => `${x.label} ${x.before} → ${x.final ?? x.after}`).join(' · ')}</p>
          )}
          {(rf.rescore || []).map((x, k) => (
            <p key={k}><span className="badge bg-white text-violet-700">우선순위</span> {x.title}: S {x.before.priority} → <b>{x.after.priority}</b> — {x.reason}</p>
          ))}
          {(rf.warnings || []).length > 0 && <p className="text-amber-700">⚠ {rf.warnings.join(' · ')}</p>}
        </div>
      )}
      {rf && rf.mode === 'rule' && <p className="text-[11px] text-muted">AI 종합 판단 실패 → 영역 평가 규칙 결과 사용 ({rf.note})</p>}
      <SynthesisBox s={syn.synthesis} />
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-2">
        {a.agents.map((g) => (
          <div key={g.agent} className={`rounded-xl px-3 py-2 text-xs ${g.active ? 'bg-navy-50 ring-1 ring-navy-100' : 'bg-slate-50 text-slate-400'}`}>
            <p className="font-bold text-navy-900">{g.label}{!g.active && <span className="ml-1 font-normal">· 해당 없음</span>}</p>
            {g.active && <p className="mt-0.5 text-navy-700 leading-5">{g.summary || '특이 사항 없음'}</p>}
            {g.active && <AgentLlm g={g} />}
          </div>
        ))}
      </div>
      {pri.length > 0 && (
        <div>
          <p className="text-xs font-bold text-muted mb-1">우선순위 — 높을수록 대체찬을 먼저 배분 (Stage 3)</p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs min-w-[640px]">
              <tbody>
                {pri1.length > 0 && (
                  <tr><td colSpan={6} className="pt-1 pb-0.5 text-[11px] font-bold text-rose-700">Level 1 · 안전성 — 알레르기·연하 안전·약물 상호작용, 점수와 무관하게 최우선 확인</td></tr>
                )}
                {pri1.map((i, k) => <PriorityRow key={`a${k}`} i={i} />)}
                {pri2.length > 0 && (
                  <tr><td colSpan={6} className="pt-2 pb-0.5 text-[11px] font-bold text-navy-700">Level 2 · 영양 중재 — {pareto ? '파레토 묶음(심각도·시급성·개선 가능성) → 묶음 안에서 ' : ''}S = 0.5×심각도 + 0.3×시급성 + 0.2×개선 가능성 순</td></tr>
                )}
                {pri2.slice(0, Math.max(3, 8 - pri1.length)).map((i, k) => <PriorityRow key={`b${k}`} i={i} />)}
              </tbody>
            </table>
          </div>
        </div>
      )}
      <div className="grid md:grid-cols-2 gap-3">
        <div>
          <p className="text-xs font-bold text-muted mb-1">개인 영양 기준 (끼니) · 정한 기준 <span className="font-normal">— KDRI 공통 + 질환(식단형 규격·학회 지침) 중 가장 엄격한 값, 마우스를 올리면 후보</span></p>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(syn.constraints || {}).map(([k, c]) => {
              const [lab, op, unit] = FIELD_LABEL[k] || [k, '', '']
              return (
                <span key={k} className="badge bg-white ring-1 ring-navy-100 text-navy-800" title={`근거: ${SRC_SHORT[c.source] || c.source || '-'}${(c.candidates || []).length > 1 ? `\n후보(가장 엄격한 값 선택): ${c.candidates.map((x) => `${SRC_SHORT[x.source] || x.source} ${Math.round(x.value * 10) / 10}`).join(' · ')}` : c.others?.length ? ` · 같은 항목 제시: ${c.others.map((o) => AGENT_LABEL[o] || o).join(', ')}` : ''}`}>
                  {lab} {op}{Math.round(c.value * 10) / 10}{unit} <span className="text-muted">· {agentName(c.agent)}</span>
                  {c.specialist_from != null && <span className="text-teal-600" title={`충돌 전문가 조정 ${c.specialist_from} → ${c.value}`}> ‡</span>}
                  {c.locked_by && <span className="text-rose-600" title={`${c.locked_by} — 1단계 값으로 고정`}> 🔒</span>}
                  {c.energy_rescaled_from != null && <span className="text-violet-600" title={`목표 열량 변경으로 ${c.energy_rescaled_from} → 재계산`}> ↻</span>}
                </span>
              )
            })}
          </div>
        </div>
        <div>
          <p className="text-xs font-bold text-muted mb-1">피할 식재료 (대체찬·제품에서 제외)</p>
          {(syn.avoid || []).length ? syn.avoid.map((x, k) => (
            <p key={k} className="text-xs leading-5"><b className="text-rose-700">{x.reason}</b> <span className="text-muted">— {x.keywords.slice(0, 10).join(', ')}{x.keywords.length > 10 ? ' …' : ''}{x.min_g ? ` (한 메뉴 ${x.min_g}g 이상)` : ''}</span></p>
          )) : <p className="text-xs text-muted">없음</p>}
          {(syn.notes || []).length > 0 && (
            <>
              <p className="text-xs font-bold text-muted mt-2 mb-1">복약·돌봄 안내</p>
              {syn.notes.map((n, k) => <p key={k} className="text-xs text-navy-700 leading-5">· {n}</p>)}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

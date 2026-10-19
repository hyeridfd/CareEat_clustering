import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import api from '../../lib/api'
import { errMsg, fmtDate } from './CareUI'

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
      <ol className="mt-5 grid grid-cols-2 md:grid-cols-6 gap-2">
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

function Section({ title, right, children, className = '' }) {
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

export default function DietDesign() {
  const [status, setStatus] = useState(null)
  const [runId, setRunId] = useState(null)
  const [run, setRun] = useState(null)
  const [sub, setSub] = useState('menu')
  const [preset, setPreset] = useState('standard')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  const loadStatus = () => api.get('/care/diet/status').then((r) => {
    setStatus(r.data)
    setRunId((cur) => cur || r.data.runs?.find((x) => ['done', 'approved'].includes(x.status))?.id || r.data.runs?.[0]?.id || null)
    return r.data
  }).catch((e) => setErr(errMsg(e)))

  const loadRun = (id) => id && api.get(`/care/diet/runs/${id}`, { timeout: 60000 }).then((r) => setRun(r.data)).catch((e) => setErr(errMsg(e)))

  useEffect(() => { loadStatus() }, [])
  useEffect(() => { setRun(null); loadRun(runId) }, [runId])

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
      const r = await api.post('/care/diet/runs', { preset })
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
        {!ready && <p className="mt-3 text-xs text-muted">진단 화면에서 어르신 평가를 먼저 실행해야 식단을 설계할 수 있습니다.</p>}
        {status?.runs?.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {status.runs.map((x) => (
              <button key={x.id} onClick={() => setRunId(x.id)}
                className={`rounded-xl px-3 py-1.5 text-xs text-left ring-1 ${runId === x.id ? 'ring-navy-500 bg-navy-50' : 'ring-navy-100 bg-white hover:ring-navy-300'}`}>
                <span className="font-semibold text-navy-900">{fmtDate(x.created_at)} {new Date(x.created_at).toTimeString().slice(0, 5)}</span>
                <span className={`badge ml-1.5 ${RUN_STATUS[x.status]?.cls}`}>{RUN_STATUS[x.status]?.label}</span>
                {x.parent_run_id && <span className="ml-1 text-muted">수정본</span>}
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
      ) : (
        <SubsTab run={live} />
      )}
    </div>
  )
}

/* ─────────────────────────── ① 식단표 ─────────────────────────── */

function MenuTab({ run, onApprove, onEdited, onRerun, setErr }) {
  const [askStart, setAskStart] = useState(false)
  const [startDate, setStartDate] = useState(run.start_date || run.params?.start_date || (() => {
    const d = new Date(Date.now() + 9 * 3600e3); d.setUTCDate(d.getUTCDate() + 1); return d.toISOString().slice(0, 10)
  })())
  const [week, setWeek] = useState(1)
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
  const nEdits = Object.keys(edits).length

  const saveEdits = async () => {
    setSaving(true); setErr('')
    try {
      const changes = Object.entries(edits).map(([k, v]) => { const [일차, 끼니, 칸] = k.split('|'); return { 일차, 끼니, 칸, 메뉴: v } })
      const r = await api.put(`/care/diet/runs/${run.id}/menu`, { changes })
      setEdits({}); onEdited(r.data.id)
    } catch (e) { setErr(errMsg(e)) } finally { setSaving(false) }
  }

  return (
    <div className="space-y-4">
      <Section title="설계 결과"
        right={<>
          {run.status === 'approved'
            ? <span className="badge bg-emerald-50 text-emerald-700">승인됨 · {fmtDate(run.approved_at)}{run.start_date ? ` · ${run.start_date} 시작` : ''}</span>
            : askStart ? (
              <span className="flex items-center gap-2 rounded-xl bg-navy-50 px-2 py-1">
                <span className="text-xs text-navy-700">식단 1일차</span>
                <input type="date" className="form-input !py-1 !w-auto" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                <button className="btn-primary text-xs" disabled={!startDate} onClick={() => { setAskStart(false); onApprove(startDate) }}>승인 확정</button>
                <span className="text-[11px] text-muted">주간 발주량이 입고로 재고에 기록됩니다</span>
                <button className="btn-ghost text-xs" onClick={() => setAskStart(false)}>취소</button>
              </span>
            ) : <button className="btn-primary" onClick={() => setAskStart(true)} disabled={nEdits > 0}>영양사 승인</button>}
          <button className="btn-secondary" onClick={onRerun}>다시 최적화</button>
        </>}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Stat label="f1 영양 위반" value={sel['f1_영양위반']} sub="기본 일반식 기준 · 0.3 이하 목표" tone={sel['f1_영양위반'] <= 0.3 ? 'bg-emerald-50' : 'bg-amber-50'} />
          <Stat label="f2 예산·재고" value={sel['f2_예산·재고']} sub={m.inventory_unused != null ? `재고 미활용률 ${m.inventory_unused}` : '재고 미입력'} />
          <Stat label="f3 다양성·선호" value={sel['f3_다양성·선호']} sub="80 이상 목표" />
          <Stat label="f4 패턴 위반" value={sel['f4_패턴위반']} sub="0.1 이하 목표" />
          <Stat label="파레토 해 품질(HV)" value={m.front?.hv?.toFixed?.(3) ?? '–'} sub={m.front ? `비지배해 ${m.front.n_nondom}개 · f1 통과 ${m.front.f1_pass_rate}%` : '수정본은 계산 안 함'} />
          <Stat label="배식 기준 충족" value={pct(ss.끼니 - ss.조정불가, ss.끼니)} unit="%" sub={`나트륨 ${pct(ss.나트륨OK, ss.끼니) ?? '–'}% · 열량 ${pct(ss.열량OK, ss.끼니) ?? '–'}%`} />
          <Stat label="대체찬" value={res.substitutions?.length ?? 0} unit="건" sub={`${(res.residents || []).filter((x) => x.substitutions > 0).length}명 대상`} />
          <Stat label="설계 어르신" value={run.result?.residents?.length} unit="명" sub={m.optimize_sec ? `최적화 ${m.optimize_sec}초` : run.parent_run_id ? '영양사 수정본' : ''} />
        </div>
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-navy-700 font-semibold">영양 위반 기여도 · 식단 규칙 점검 · 재고 활용</summary>
          <div className="mt-3 grid md:grid-cols-3 gap-4">
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
        </details>
      </Section>

      <Section title="28일 일반식 식단표"
        right={<>
          {[1, 2, 3, 4].map((w) => (
            <button key={w} onClick={() => setWeek(w)} className={`px-3 py-1 rounded-full text-xs font-semibold ${week === w ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>{w}주</button>
          ))}
          {nEdits > 0 && <>
            <span className="text-xs text-amber-700">수정 {nEdits}건</span>
            <button className="btn-ghost text-xs" onClick={() => setEdits({})}>취소</button>
            <button className="btn-primary text-xs" disabled={saving} onClick={saveEdits}>{saving ? '저장 중…' : '수정본 계산'}</button>
          </>}
        </>}>
        <p className="mb-3 text-xs text-muted">메뉴를 누르면 같은 칸의 후보 메뉴로 바꿀 수 있습니다. 수정본을 계산하면 대체찬·배식량이 새 식단 기준으로 다시 계산됩니다.</p>
        <div className="overflow-x-auto">
          <table className="w-full text-[13px] min-w-[980px]">
            <thead>
              <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                <th className="py-2 pr-2">일차</th><th className="py-2 pr-2">끼니</th>
                {SLOTS.map((s) => <th key={s} className="py-2 pr-2">{s}</th>)}
                <th className="py-2 pr-2 text-right">열량</th><th className="py-2 pr-2 text-right">나트륨</th><th className="py-2 pr-2 text-right">단백질</th>
                <th className="py-2">다진찬 주의</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.일차 + r.끼니} className={`border-b border-navy-50 align-top ${r.끼니 === '저녁' ? 'border-b-navy-100' : ''}`}>
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
                            className={`text-left rounded px-1 -mx-1 hover:bg-navy-50 ${edits[k] ? 'bg-amber-50 text-amber-900 font-semibold' : ''}`}>{v}</button>
                        )}
                      </td>
                    )
                  })}
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r['열량(kcal)']}</td>
                  <td className={`py-1.5 pr-2 text-right tabular-nums ${r['나트륨(mg)'] > 600 ? 'text-rose-600 font-semibold' : ''}`}>{r['나트륨(mg)']}</td>
                  <td className="py-1.5 pr-2 text-right tabular-nums">{r['단백질(g)']}</td>
                  <td className="py-1.5 text-[11px] text-muted">{r.다진찬주의 === '-' ? '' : r.다진찬주의}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}

/* ─────────────────────────── ② 개인 배식표 ─────────────────────────── */

function ServingTab({ run }) {
  const residents = run.result?.residents || []
  const [q, setQ] = useState('')
  const [eid, setEid] = useState(residents[0]?.elderly_id || null)
  const [meals, setMeals] = useState(null)
  const [day, setDay] = useState('all')
  const [err, setErr] = useState('')

  useEffect(() => {
    if (!eid) return
    setMeals(null); setErr('')
    api.get(`/care/diet/runs/${run.id}/servings/${eid}`).then((r) => setMeals(r.data.meals)).catch((e) => setErr(errMsg(e)))
  }, [eid, run.id])

  const list = residents.filter((r) => !q || r.display_name.includes(q))
  const me = residents.find((r) => r.elderly_id === eid)
  const shown = (meals || []).filter((x) => day === 'all' || x.일차 === day)
  const days = [...new Set((meals || []).map((x) => x.일차))]

  return (
    <div className="grid md:grid-cols-[260px_1fr] gap-4">
      <div className="surface p-3 max-h-[720px] overflow-y-auto">
        <input className="form-input !py-2 mb-2" placeholder="이름 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        {list.map((r) => {
          const s = r.serving || {}
          return (
            <button key={r.elderly_id} onClick={() => setEid(r.elderly_id)}
              className={`w-full text-left rounded-xl px-3 py-2 mb-1 ${eid === r.elderly_id ? 'bg-navy-900 text-white' : 'hover:bg-navy-50'}`}>
              <span className="text-sm font-semibold">{r.display_name}</span>
              <span className={`ml-1.5 text-[11px] ${eid === r.elderly_id ? 'text-navy-100' : 'text-muted'}`}>{r.type} · {r.texture}</span>
              <span className={`block text-[11px] ${eid === r.elderly_id ? 'text-navy-100' : 'text-muted'}`}>
                대체 {r.substitutions}건 · 기준 충족 {pct((s.끼니 || 0) - (s.조정불가 || 0), s.끼니) ?? '–'}%{r.no_spicy ? ' · 백김치' : ''}
              </span>
            </button>
          )
        })}
      </div>
      <div className="space-y-4 min-w-0">
        {me && (
          <Section title={`${me.display_name} 님 배식표`}
            right={<select className="form-select !py-1.5 !w-auto" value={day} onChange={(e) => setDay(e.target.value)}>
              <option value="all">28일 전체</option>
              {days.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <Stat label="질환 유형" value={me.type} sub={me.diseases?.join(' · ') || '해당 없음'} />
              <Stat label="식사 형태" value={me.texture} sub={me.no_spicy ? '매운 음식 불가 → 백김치' : ''} />
              <Stat label="목표 열량" value={Math.round(me.target_energy)} unit="kcal/끼" sub={`나트륨 상한 ${me.sodium_max}mg/끼`} />
              <Stat label="대체찬" value={me.substitutions} unit="건" sub={Object.entries(me.reasons || {}).slice(0, 2).map(([k, v]) => `${k} ${v}`).join(' · ')} />
            </div>
            {err && <p className="text-sm text-rose-700">{err}</p>}
            {!meals ? <p className="text-sm text-muted">불러오는 중…</p> : (
              <div className="overflow-x-auto">
                <table className="w-full text-[13px] min-w-[1000px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                      <th className="py-2 pr-2">일차</th><th className="py-2 pr-2">끼니</th>
                      {SLOTS.map((s) => <th key={s} className="py-2 pr-2">{s}</th>)}
                      <th className="py-2 pr-2 text-right">열량</th><th className="py-2 pr-2 text-right">단백질</th><th className="py-2 pr-2 text-right">나트륨</th>
                      <th className="py-2 pr-2">기준</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shown.map((x) => {
                      const ratio = Object.fromEntries((x.칸별비율 || '').split(' ').map((t) => {
                        const mm = t.match(/^(밥|국|주찬|부찬1|부찬2|김치)([\d.]+)/); return mm ? [mm[1], mm[2]] : [t, '']
                      }))
                      return (
                        <tr key={x.일차 + x.끼니} className="border-b border-navy-50 align-top">
                          <td className="py-1.5 pr-2 font-semibold text-navy-900 whitespace-nowrap">{x.일차}</td>
                          <td className="py-1.5 pr-2 text-muted">{x.끼니}</td>
                          {SLOTS.map((s) => {
                            const changed = (x.대체 || []).includes(s) || (x.식사형태변경 || []).includes(s)
                            const g = x[s]
                            return (
                              <td key={s} className="py-1.5 pr-2">
                                <span className={`block leading-5 ${(x.대체 || []).includes(s) ? 'text-emerald-800 font-semibold' : changed ? 'text-navy-700 font-semibold' : 'text-navy-900'}`}>
                                  {x.메뉴?.[s]}
                                </span>
                                <span className="text-[11px] text-muted tabular-nums">{g ? `${g}g` : '미배식'}{ratio[s] && g ? ` · ×${Number(ratio[s])}` : ''}</span>
                              </td>
                            )
                          })}
                          <td className="py-1.5 pr-2 text-right tabular-nums">{x.예상열량}</td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">{x.예상단백질}</td>
                          <td className="py-1.5 pr-2 text-right tabular-nums">{x.예상나트륨}</td>
                          <td className="py-1.5 pr-2 text-[11px] whitespace-nowrap">
                            {String(x.조정결과).startsWith('조정불가')
                              ? <span className="text-amber-700">일부 초과</span>
                              : <span className="text-emerald-600">충족</span>}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <p className="mt-2 text-[11px] text-muted">초록 글씨 = 고령친화식품 대체(1인분 그대로) · 파란 글씨 = 죽·백김치 · 배식량은 0·0.25·0.5·0.75·1·1.25·1.5·2배 단계</p>
              </div>
            )}
          </Section>
        )}
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
        고령친화식품의 선호까지 예측합니다. 점수는 다음 식단 설계의 다양성·선호 목표(f3)와 대체 제품 선택에 쓰입니다.
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
                <span>승인 식단의 <b>주간 발주량</b>을 각 주 1일차 전날 <b>입고</b>로 기록하면, 실사 없이도 매일 남은 양이 계산됩니다. (다시 누르면 자동입고를 새로 계산)</span>
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
            { key: '7일사용(g)', label: '7일 사용 예정', right: true, render: (r) => kg(r['7일사용(g)']) },
          ]} />
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
      const body = { date, kind, items: rows.filter((r) => r.식재료명 && r.수량 !== '').map((r) => ({ ...r, 수량: Number(r.수량), 유통기한: r.유통기한 || null })) }
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
        <textarea className="form-input !py-1.5 text-xs flex-1 min-w-[240px]" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)}
          placeholder="엑셀에서 '식재료명 · 양(g) · 유통기한' 열을 복사해 붙여넣기" />
        <button className="btn-secondary text-xs" disabled={!paste.trim()} onClick={addPaste}>붙여넣은 행 추가</button>
      </div>
      {msg && <p className="mt-2 text-xs text-navy-700">{msg}</p>}
    </Section>
  )
}

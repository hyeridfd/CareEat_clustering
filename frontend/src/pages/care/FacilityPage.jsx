import { useEffect, useMemo, useState } from 'react'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { errMsg } from '../../components/care/CareUI'

/* Care-Eat Scan — 시설 영양 프로파일
   개인 평가를 시설 단위로 집계해 "우리 시설은 무엇이 문제인가"를 보여준다. */

const TONE = (pct, cut = [15, 30]) =>
  pct == null ? 'bg-slate-200' : pct >= cut[1] ? 'bg-rose-500' : pct >= cut[0] ? 'bg-amber-500' : 'bg-navy-500'

function Stat({ label, value, unit, sub, tone }) {
  return (
    <div className={`rounded-2xl px-4 py-3.5 ${tone || 'bg-navy-50/70'}`}>
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 text-2xl font-extrabold tabular-nums text-navy-900">
        {value ?? '–'}<span className="ml-0.5 text-xs font-normal text-muted">{unit}</span>
      </p>
      {sub && <p className="mt-0.5 text-[11px] text-muted">{sub}</p>}
    </div>
  )
}

const SEV = {
  3: { label: '시급', chip: 'bg-rose-100 text-rose-800', bar: 'bg-rose-500' },
  2: { label: '주의', chip: 'bg-amber-100 text-amber-900', bar: 'bg-amber-500' },
  1: { label: '관찰', chip: 'bg-slate-100 text-slate-600', bar: 'bg-slate-400' },
}

/* 관리 우선순위 — "왜 이 순위인가"를 점수 산식까지 드러낸다 */
function PriorityCard({ x }) {
  const sev = SEV[x.severity] || SEV[1]
  return (
    <li className="rounded-2xl ring-1 ring-navy-100 bg-white p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex items-center justify-center w-7 h-7 shrink-0 rounded-lg bg-navy-900 text-white text-xs font-extrabold tabular-nums">{x.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="badge bg-navy-50 text-navy-700">{x.area_label}</span>
            <span className={`badge ${sev.chip}`}>{sev.label}</span>
            <span className="ml-auto text-[11px] text-muted tabular-nums">
              규모 {x.impact}% × {sev.label} = <b className="text-navy-900">{x.score}점</b>
            </span>
          </div>
          <p className="mt-2 text-[15px] font-bold leading-6 text-navy-900">{x.title}</p>
          <p className="mt-1.5 text-sm leading-6 text-slate-700">{x.detail}</p>
          {x.basis && <p className="mt-0.5 text-xs text-muted">{x.basis}</p>}
          <div className="mt-2 h-1.5 rounded-full bg-navy-50">
            <div className={`h-1.5 rounded-full ${sev.bar}`} style={{ width: `${Math.max(3, Math.min(100, x.score))}%` }} />
          </div>
          {x.action && (
            <p className="mt-3 rounded-xl bg-navy-50/70 px-4 py-2.5 text-sm leading-6 text-navy-900">
              <b className="text-navy-500 text-xs mr-1.5">해야 할 일</b>{x.action}
            </p>
          )}
        </div>
      </div>
    </li>
  )
}

const TABS = [
  { key: 'scan', label: '시설 진단', desc: '지금 우리 시설은 어떤가' },
  { key: 'priority', label: '관리 우선순위', desc: '무엇부터 바꿔야 하는가' },
  { key: 'action', label: '개선안', desc: '다음 주 식단을 어떻게 바꾸나' },
]

function Tabs({ tab, onChange, counts }) {
  return (
    <div className="surface p-1.5 flex gap-1.5">
      {TABS.map((t) => {
        const on = tab === t.key
        return (
          <button key={t.key} onClick={() => onChange(t.key)}
            className={`flex-1 rounded-xl px-4 py-2.5 text-left transition ${on ? 'bg-navy-900 text-white' : 'hover:bg-navy-50'}`}>
            <span className="flex items-center gap-2">
              <span className={`text-sm font-bold ${on ? 'text-white' : 'text-navy-900'}`}>{t.label}</span>
              {counts?.[t.key] != null && (
                <span className={`badge ${on ? 'bg-white/20 text-white' : 'bg-navy-50 text-navy-700'}`}>{counts[t.key]}</span>
              )}
            </span>
            <span className={`block mt-0.5 text-[11px] ${on ? 'text-navy-100/80' : 'text-muted'}`}>{t.desc}</span>
          </button>
        )
      })}
    </div>
  )
}

/* ── Care-Eat Action ──────────────────────────────────────────────
   우선순위 하나에 ① 공식 지침 근거 ② 식품 DB 메뉴 후보 ③ 잔반 메뉴 대체안을 붙인다. */

function MenuChip({ it, delta }) {
  const metric =
    it.amount != null ? `${it.amount}${it.unit || ''}`
      : it.sodium_mg != null ? `나트륨 ${it.sodium_mg}mg`
        : ''
  const warn = []
  if (it.sodium_underestimated) warn.push(`나트륨 과소 (${it.sodium_underestimated.slice(0, 2).join(' · ')} 자료 없음)`)
  if (it.amount_outlier) warn.push('레시피 분량 확인 필요')
  if (it.broth_missing) warn.push('국물 미등록 — 중량은 건더기뿐')
  return (
    <li className="rounded-xl ring-1 ring-navy-100 bg-white px-3.5 py-2.5">
      <div className="flex items-center gap-1.5">
        {it.meal_cat && <span className="badge bg-navy-50 text-navy-700">{it.meal_cat}</span>}
        <span className="text-sm font-bold text-navy-900 truncate">{it.title}</span>
        {metric && <span className="ml-auto shrink-0 text-[11px] font-bold tabular-nums text-navy-900">{metric}</span>}
      </div>
      <p className="mt-1 text-[11px] tabular-nums text-muted">
        1인분 {it.serving_g}g
        {it.energy_kcal != null && ` · ${it.energy_kcal}kcal`}
        {it.amount != null && it.sodium_mg != null && ` · 나트륨 ${it.sodium_mg}mg`}
      </p>
      {delta && (
        <p className="mt-1 text-[11px] tabular-nums">
          <span className={delta.sodium_mg <= 0 ? 'text-navy-700' : 'text-rose-700'}>
            나트륨 {delta.sodium_mg > 0 ? '+' : ''}{delta.sodium_mg}mg
          </span>
          <span className="mx-1 text-slate-300">|</span>
          <span className={delta.protein_g >= 0 ? 'text-navy-700' : 'text-amber-700'}>
            단백질 {delta.protein_g > 0 ? '+' : ''}{delta.protein_g}g
          </span>
          <span className="mx-1 text-slate-300">|</span>
          <span className="text-muted">{delta.energy_kcal > 0 ? '+' : ''}{delta.energy_kcal}kcal</span>
        </p>
      )}
      {it.key_ingredients?.length > 0 && (
        <p className="mt-1 text-[11px] text-muted truncate">{it.key_ingredients.join(' · ')}</p>
      )}
      {it.salty_ingredients?.length > 0 && (
        <p className="mt-1 text-[11px] text-muted truncate">간이 센 재료 {it.salty_ingredients.join(' · ')}</p>
      )}
      {it.caution_ingredients?.length > 0 && (
        <p className="mt-0.5 text-[11px] text-amber-700 truncate">
          확인 필요: {it.caution_ingredients.slice(0, 3).join(' · ')}
        </p>
      )}
      {warn.map((w, i) => <p key={i} className="mt-0.5 text-[11px] text-rose-700 truncate">※ {w}</p>)}
    </li>
  )
}

function MenuBlock({ m }) {
  if (!m) return null
  if (m.kind === 'replace') {
    return (
      <div className="mt-3 rounded-xl bg-navy-50/50 p-4">
        <p className="text-xs font-bold text-navy-900">{m.purpose}</p>
        <ul className="mt-2.5 space-y-2.5">
          {m.swaps.map((s, i) => (
            <li key={i}>
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-sm font-bold text-navy-900">{s.current}</span>
                {s.current_rate != null && (
                  <span className="text-[11px] tabular-nums text-rose-700">섭취율 {s.current_rate}%{s.current_n ? ` · ${s.current_n}건` : ''}</span>
                )}
                {s.meal_cat && <span className="badge bg-white text-navy-700">{s.meal_cat} 자리</span>}
              </div>
              {s.current_nutrition && (
                <p className="mt-0.5 text-[11px] tabular-nums text-muted">
                  현재 1인분 {s.current_nutrition.serving_g}g · {s.current_nutrition.energy_kcal}kcal ·
                  단백질 {s.current_nutrition.protein_g}g · 나트륨 {s.current_nutrition.sodium_mg}mg
                </p>
              )}
              {s.note
                ? <p className="mt-1 text-[11px] text-amber-700">{s.note}</p>
                : <ul className="mt-1.5 grid sm:grid-cols-2 gap-1.5">{s.candidates.map((c) => <MenuChip key={c.id} it={c} delta={c.delta} />)}</ul>}
            </li>
          ))}
        </ul>
      </div>
    )
  }
  return (
    <div className="mt-3 rounded-xl bg-navy-50/50 p-4">
      <p className="text-xs font-bold text-navy-900">{m.purpose}</p>
      {m.basis && <p className="mt-0.5 text-[11px] text-muted">{m.basis}</p>}
      <ul className="mt-2.5 grid sm:grid-cols-2 gap-1.5">
        {m.items.map((it) => <MenuChip key={it.id} it={it} />)}
      </ul>
    </div>
  )
}

function ActionCard({ x }) {
  return (
    <li className="rounded-2xl ring-1 ring-navy-100 bg-white p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex items-center justify-center w-7 h-7 shrink-0 rounded-lg bg-navy-900 text-white text-xs font-extrabold tabular-nums">{x.rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="badge bg-navy-50 text-navy-700">{x.area_label}</span>
            <span className="badge bg-slate-100 text-slate-600">{x.severity_label}</span>
            <span className="ml-auto text-[11px] tabular-nums text-muted">{x.score}점</span>
          </div>
          <p className="mt-2 text-[15px] font-bold leading-6 text-navy-900">{x.title}</p>
          <p className="mt-1 text-xs text-muted">{x.detail}</p>

          {x.action && (
            <p className="mt-3 rounded-xl bg-navy-50/70 px-4 py-2.5 text-sm leading-6 text-navy-900">
              <b className="text-navy-500 text-xs mr-1.5">해야 할 일</b>{x.action}
            </p>
          )}

          {x.guidelines?.length > 0 && (
            <div className="mt-3 space-y-2">
              <p className="text-xs font-bold text-navy-900">근거 지침</p>
              {x.guidelines.map((gl) => (
                <blockquote key={gl.tag} className="rounded-xl border-l-2 border-navy-200 bg-white px-3.5 py-2">
                  <p className="text-[13px] leading-6 text-slate-700">
                    <sup className="mr-1 font-bold text-navy-600">{gl.tag.replace('G', '')}</sup>{gl.text}
                  </p>
                  <p className="mt-1 text-[11px] text-muted">{gl.source}</p>
                </blockquote>
              ))}
            </div>
          )}

          <MenuBlock m={x.menus} />
        </div>
      </div>
    </li>
  )
}

function Section({ title, sub, right, children }) {
  return (
    <section className="surface p-6">
      <header className="flex flex-wrap items-end justify-between gap-2 mb-4">
        <div>
          <h2 className="text-base font-extrabold text-navy-900">{title}</h2>
          {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  )
}

/* 비율 막대 — 위험군·질환처럼 '몇 %가 해당되는가' */
function RatioRows({ rows, cut, denom, empty = '해당 항목이 없습니다.' }) {
  const shown = rows.filter((r) => r.pct)
  if (!shown.length) return <p className="text-sm text-muted py-2">{empty}</p>
  return (
    <div className="space-y-2">
      {shown.map((r) => {
        const den = r.denom ?? denom
        const thin = den != null && den < 5      // 분모가 작으면 비율을 믿을 수 없다
        return (
          <div key={r.key || r.name} className="flex items-center gap-3">
            <span className="w-52 shrink-0 text-xs text-gray-700 truncate">{r.label || r.name}</span>
            <div className="relative h-3 flex-1 rounded-full bg-navy-50 min-w-0">
              <div className={`absolute inset-y-0 left-0 rounded-full ${thin ? 'bg-slate-300' : TONE(r.pct, cut)}`}
                style={{ width: `${Math.max(2, Math.min(100, r.pct))}%` }} />
            </div>
            <span className="w-28 shrink-0 text-right text-[11px] tabular-nums text-muted">
              <b className={thin ? 'text-slate-400' : 'text-navy-900'}>{r.pct}%</b>
              <span className="ml-1">{r.n}{den != null ? `/${den}` : ''}명</span>
            </span>
          </div>
        )
      })}
    </div>
  )
}

/* 섭취율 막대 — 낮을수록 문제 */
function IntakeRows({ rows, labelKey = 'label' }) {
  if (!rows?.length) return <p className="text-sm text-muted py-2">식사 기록이 없습니다.</p>
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="w-28 shrink-0 text-xs text-gray-700 truncate">{r[labelKey]}</span>
          <div className="relative h-3 flex-1 rounded-full bg-navy-50 min-w-0">
            <div className={`absolute inset-y-0 left-0 rounded-full ${r.rate ?? r.value ? ((r.rate ?? r.value) < 60 ? 'bg-rose-500' : (r.rate ?? r.value) < 80 ? 'bg-amber-500' : 'bg-navy-500') : 'bg-slate-200'}`}
              style={{ width: `${Math.max(2, Math.min(100, r.rate ?? r.value ?? 0))}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-muted">
            <b className="text-navy-900">{r.rate ?? r.value ?? '–'}%</b>{r.n ? ` · ${r.n}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function FacilityPage() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [tab, setTab] = useState('scan')
  const [area, setArea] = useState('all')
  const [act, setAct] = useState(null)
  const [actBusy, setActBusy] = useState(false)
  const [actErr, setActErr] = useState('')

  // 개선안은 지침 검색(RAG)이 들어가 느리다 → 탭을 열 때 한 번만 만든다
  const loadAction = (force = false) => {
    if (actBusy || (act && !force)) return
    setActBusy(true); setActErr('')
    api.get('/care/facility/action', { params: { top: 5, refresh: force }, timeout: 120000 })
      .then((r) => setAct(r.data))
      .catch((e) => setActErr(errMsg(e)))
      .finally(() => setActBusy(false))
  }

  const load = (refresh = false) => {
    setBusy(true)
    api.get('/care/facility/profile', { params: refresh ? { refresh: true } : {}, timeout: 60000 })
      .then((r) => { setD(r.data); setErr('') })
      .catch((e) => setErr(errMsg(e)))
      .finally(() => setBusy(false))
  }
  useEffect(() => { load() }, [])

  const risk = (k) => d?.risks?.find((x) => x.key === k)?.pct
  const nutDenom = d?.nutrients?.length ? Math.max(...d.nutrients.map((x) => x.denom || 0)) : null
  const g = d?.data_gaps
  const areas = useMemo(() => {
    const m = new Map()
    for (const x of d?.priorities || []) m.set(x.area, x.area_label)
    return [...m].map(([key, label]) => ({ key, label }))
  }, [d])
  const shownPriorities = (d?.priorities || []).filter((x) => area === 'all' || x.area === area)

  return (
    <CareLayout
      title="시설 진단"
      subtitle="입소자 평가를 시설 단위로 모아, 급식·영양 운영에서 무엇부터 봐야 할지 정리합니다."
      actions={<button onClick={() => load(true)} disabled={busy} className="btn-secondary text-sm">{busy ? '집계 중…' : '다시 집계'}</button>}
    >
      {err && <p className="surface p-6 text-red-700">{err}</p>}
      {!err && !d && <div className="surface p-12 text-center text-muted">불러오는 중…</div>}

      {d && (
        <div className="space-y-5">
          <Tabs tab={tab} onChange={(t) => { setTab(t); if (t === 'action') loadAction() }} counts={{ priority: d.priorities?.length || 0, action: act?.plans?.length ?? null }} />

          {tab === 'priority' && (
            <>
              <Section title="관리 우선순위"
                sub="규모(해당 어르신 비율)와 심각도를 곱해 매긴 순서입니다. 위에서부터 손대는 것이 효율적입니다."
                right={areas.length > 1 && (
                  <div className="flex flex-wrap gap-1">
                    <button onClick={() => setArea('all')}
                      className={`badge ${area === 'all' ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>전체 {d.priorities.length}</button>
                    {areas.map((a) => (
                      <button key={a.key} onClick={() => setArea(a.key)}
                        className={`badge ${area === a.key ? 'bg-navy-900 text-white' : 'bg-navy-50 text-navy-700'}`}>
                        {a.label} {d.priorities.filter((x) => x.area === a.key).length}
                      </button>
                    ))}
                  </div>
                )}>
                {shownPriorities.length ? (
                  <ol className="space-y-3">{shownPriorities.map((x) => <PriorityCard key={x.id} x={x} />)}</ol>
                ) : (
                  <p className="text-sm text-muted py-2">
                    {d.priorities?.length ? '이 영역에는 해당 항목이 없습니다.' : '기준을 넘는 문제가 탐지되지 않았습니다.'}
                  </p>
                )}
              </Section>
              <p className="text-[11px] text-muted px-1">
                점수는 규모(해당 어르신 비율) × 심각도(시급 3 / 주의 2 / 관찰 1) ÷ 3 입니다.
                다음 단계(Action)에서는 각 항목에 공식 지침 근거와 식품·메뉴 DB를 연결해 바꿀 메뉴까지 제시합니다.
              </p>
            </>
          )}

          {tab === 'action' && (
            <>
              <Section title="실행 개선안"
                sub="우선순위 상위 항목에 공식 지침 근거와 식품·메뉴 DB의 후보를 붙였습니다. 제공량 산정과 최종 채택은 영양사가 합니다."
                right={<button onClick={() => loadAction(true)} disabled={actBusy} className="btn-secondary text-sm">{actBusy ? '만드는 중…' : '다시 만들기'}</button>}>
                {actErr && <p className="text-sm text-red-700 py-2">{actErr}</p>}
                {!actErr && actBusy && !act && (
                  <p className="text-sm text-muted py-6 text-center">지침을 찾고 메뉴 후보를 고르는 중입니다… (30초쯤 걸립니다)</p>
                )}
                {act && (
                  <>
                    <div className="flex flex-wrap gap-1.5 mb-4">
                      <span className="badge bg-navy-50 text-navy-700">우선순위 {act.plans?.length ?? 0}건</span>
                      <span className={`badge ${act.rag_enabled ? 'bg-navy-50 text-navy-700' : 'bg-slate-100 text-slate-500'}`}>
                        지침 근거 {act.rag_enabled ? '연결됨' : '미연결'}
                      </span>
                      <span className={`badge ${act.graph ? 'bg-navy-50 text-navy-700' : 'bg-slate-100 text-slate-500'}`}>
                        식품 DB {act.graph ? `요리 ${act.graph.foods}개` : '미연결'}
                      </span>
                      {act.graph && (
                        <span className={`badge ${act.graph.source === 'neo4j' ? 'bg-emerald-50 text-emerald-800' : 'bg-amber-50 text-amber-900'}`}
                          title={act.graph.source === 'neo4j'
                            ? `Neo4j에서 직접 읽음${act.graph.age_sec != null ? ` · ${Math.round(act.graph.age_sec / 60)}분 전 갱신` : ''}`
                            : act.graph.note || '저장된 스냅샷으로 동작 중입니다'}>
                          {act.graph.source === 'neo4j' ? '실시간 연결' : '스냅샷'}
                        </span>
                      )}
                      {act.diseases_applied?.length > 0 && (
                        <span className="badge bg-amber-50 text-amber-900">금기 검증 {act.diseases_applied.join(' · ')}</span>
                      )}
                    </div>
                    {act.plans?.length
                      ? <ol className="space-y-3">{act.plans.map((x) => <ActionCard key={x.id} x={x} />)}</ol>
                      : <p className="text-sm text-muted py-2">개선안을 만들 우선순위가 없습니다.</p>}
                  </>
                )}
              </Section>

              {act?.references?.length > 0 && (
                <Section title="인용한 지침" sub="개선안에 붙은 번호와 같습니다.">
                  <ol className="space-y-1.5">
                    {act.references.map((r) => (
                      <li key={r.tag} className="text-[12px] leading-6 text-slate-700">
                        <b className="mr-1.5 text-navy-700 tabular-nums">{r.tag.replace('G', '')}</b>
                        <b>{r.locator || ''}</b> {r.citation}
                        {r.short && <span className="ml-1 text-muted">({r.short})</span>}
                        {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="ml-1.5 text-navy-600 underline">원문</a>}
                      </li>
                    ))}
                  </ol>
                </Section>
              )}

              {act?.limits?.length > 0 && (
                <ul className="text-[11px] text-muted px-1 space-y-0.5">
                  {act.limits.map((t, i) => <li key={i}>· {t}</li>)}
                </ul>
              )}
            </>
          )}

          {tab === 'scan' && (
          <>
          <Section title="한눈에 보기"
            sub={`어르신 ${d.n_residents}명 중 ${d.n_assessed}명 평가 완료${d.assessed_on ? ` · 최근 평가 ${d.assessed_on}` : ''}`}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label="평가 완료" value={d.n_assessed} unit="명" sub={`전체 ${d.n_residents}명 · ${d.coverage_pct ?? '–'}%`} />
              <Stat label="평균 식사 섭취율" value={d.intake?.total} unit="%" sub={`기록 ${d.intake?.n}명`} />
              <Stat label="영양불량 위험" value={risk('malnutrition_risk')} unit="%" tone="bg-amber-50" />
              <Stat label="식형태 조정 필요" value={risk('texture_need')} unit="%" tone="bg-sky-50" />
            </div>
            {d.types?.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {d.types.map((t) => (
                  <span key={t.name} className="badge bg-navy-50 text-navy-700">{t.name} {t.n}명 ({t.pct}%)</span>
                ))}
              </div>
            )}
          </Section>

          <div className="grid lg:grid-cols-2 gap-5">
            <Section title="위험군 분포" sub="평가 완료자 기준. 비율이 높을수록 시설 차원의 대응이 필요합니다.">
              <RatioRows rows={d.risks || []} cut={[15, 30]} denom={d.n_assessed} />
            </Section>

            <Section title="진단 질환" sub="입소자에게 기록된 질환입니다.">
              <RatioRows rows={(d.diseases || []).map((x) => ({ ...x, key: x.name }))} cut={[20, 40]}
                denom={d.n_assessed} empty="기록된 질환이 없습니다." />
            </Section>
          </div>

          <Section title="영양소 기준 미달·초과"
            sub="2025 한국인 영양소 섭취기준 대비 80% 미만인 어르신의 비율입니다. 나트륨만 130% 초과 기준입니다."
            right={nutDenom != null && (
              <span className={`text-xs ${nutDenom < 5 ? 'text-rose-600 font-semibold' : 'text-muted'}`}>
                계산된 어르신 {nutDenom}명 / 평가 {d.n_assessed}명
              </span>
            )}>
            {g && (g.no_assessment || g.no_meal_log || g.nutrition_failed) > 0 && (
              <div className="mb-3 text-xs rounded-xl bg-amber-50 text-amber-900 px-3 py-2.5 space-y-1">
                <p className="font-semibold">
                  어르신 {d.n_residents}명 중 {g.nutrition_ok}명만 영양소가 계산됐습니다. 빠진 이유:
                </p>
                <ul className="space-y-0.5">
                  {g.no_assessment > 0 && (
                    <li>· <b>{g.no_assessment}명</b> — 평가를 아직 실행하지 않았습니다 (기록 화면에서 평가 실행)</li>
                  )}
                  {g.no_meal_log > 0 && (
                    <li>· <b>{g.no_meal_log}명</b> — 평가에 식사(잔반) 기록이 없습니다. 조사는 했는데 평가가 그 전이라면 재평가가 필요합니다</li>
                  )}
                  {g.nutrition_failed > 0 && (
                    <li>· <b>{g.nutrition_failed}명</b> — 식사 기록은 있으나 식단표와 연결되지 않아 영양소를 계산하지 못했습니다
                      {g.nutrition_failed_ids?.length > 0 && <span className="text-amber-700"> ({g.nutrition_failed_ids.join(', ')})</span>}
                    </li>
                  )}
                </ul>
                {nutDenom != null && nutDenom < 5 && <p className="font-semibold">표본이 너무 적어 비율을 시설 특성으로 읽으면 안 됩니다.</p>}
              </div>
            )}
            <RatioRows rows={(d.nutrients || []).map((x) => ({
              ...x, label: `${x.label} ${x.direction}`,
            }))} cut={[30, 50]} empty="섭취 영양소가 계산된 어르신이 없습니다." />
          </Section>

          <div className="grid lg:grid-cols-3 gap-5">
            <Section title="끼니별 섭취율">
              <IntakeRows rows={d.menus?.by_meal || []} />
            </Section>
            <Section title="음식군별 섭취율">
              <IntakeRows rows={d.intake?.components || []} />
            </Section>
            <Section title="식형태군별 섭취율" sub="식형태 표준화가 필요한지 확인합니다.">
              <IntakeRows rows={d.groups?.by_texture || []} />
            </Section>
          </div>

          <Section title="잔반이 많은 메뉴"
            sub="메뉴 단위 시설 평균 섭취율이 낮은 순입니다. 같은 메뉴가 여러 날 나오면 합산했습니다. 식단 개편 후보입니다."
            right={d.menus?.n_menus ? <span className="text-xs text-muted">전체 {d.menus.n_menus}종</span> : null}>
            {d.menus?.worst?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[520px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                      <th className="py-2">메뉴</th><th className="py-2">음식군</th><th className="py-2">제공</th>
                      <th className="py-2 text-right">평균 섭취율</th><th className="py-2 text-right">연인원</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.menus.worst.map((m, i) => (
                      <tr key={i} className="border-b border-navy-50 last:border-0">
                        <td className="py-2 font-semibold text-navy-900">{m.menu}</td>
                        <td className="py-2 whitespace-nowrap text-muted">{m.slot_label}</td>
                        <td className="py-2 whitespace-nowrap text-muted text-xs">{m.cells}회 · {m.meal_label}</td>
                        <td className={`py-2 text-right tabular-nums font-bold ${m.rate < 60 ? 'text-rose-600' : m.rate < 80 ? 'text-amber-700' : 'text-navy-900'}`}>{m.rate}%</td>
                        <td className="py-2 text-right tabular-nums text-muted">{m.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="text-sm text-muted py-2">식사 기록이 아직 없습니다.</p>}
          </Section>

          <p className="text-[11px] text-muted px-1">
            여기 지표가 '관리 우선순위' 탭의 점수 근거가 됩니다.
          </p>
          </>
          )}
        </div>
      )}
    </CareLayout>
  )
}

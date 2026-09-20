# -*- coding: utf-8 -*-
import io, sys, re
p = 'pages/care/FacilityPage.jsx'
s = io.open(p, encoding='utf-8').read()
assert 'ActionCard' not in s, '이미 적용됨'

# 1) 탭 추가
old_tabs = """const TABS = [
  { key: 'scan', label: '시설 진단', desc: '지금 우리 시설은 어떤가' },
  { key: 'priority', label: '관리 우선순위', desc: '무엇부터 바꿔야 하는가' },
]"""
new_tabs = """const TABS = [
  { key: 'scan', label: '시설 진단', desc: '지금 우리 시설은 어떤가' },
  { key: 'priority', label: '관리 우선순위', desc: '무엇부터 바꿔야 하는가' },
  { key: 'action', label: '개선안', desc: '다음 주 식단을 어떻게 바꾸나' },
]"""
assert old_tabs in s
s = s.replace(old_tabs, new_tabs)

# 2) Action용 컴포넌트 — Section 정의 앞에 넣는다
anchor = "function Section({ title, sub, right, children }) {"
assert anchor in s
components = r"""/* ── Care-Eat Action ──────────────────────────────────────────────
   우선순위 하나에 ① 공식 지침 근거 ② 식품 DB 메뉴 후보 ③ 잔반 메뉴 대체안을 붙인다. */

function MenuChip({ it }) {
  const metric =
    it.salt_score != null ? `염도 ${it.salt_score}`
      : it.top_value != null ? `${it.top_value} ${it.value_unit || ''}`
        : ''
  const source = it.key_ingredients?.length ? `급원 ${it.key_ingredients.join(' · ')}` : ''
  const salty = it.salty_ingredients?.length ? `간이 센 재료 ${it.salty_ingredients.join(' · ')}` : ''
  return (
    <li className="rounded-xl ring-1 ring-navy-100 bg-white px-3.5 py-2.5">
      <div className="flex items-center gap-1.5">
        {it.meal_cat && <span className="badge bg-navy-50 text-navy-700">{it.meal_cat}</span>}
        <span className="text-sm font-bold text-navy-900 truncate">{it.title}</span>
        {metric && <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted">{metric}</span>}
      </div>
      {(source || salty) && <p className="mt-1 text-[11px] text-muted truncate">{source || salty}</p>}
      {it.caution_ingredients?.length > 0 && (
        <p className="mt-0.5 text-[11px] text-amber-700 truncate">
          확인 필요: {it.caution_ingredients.slice(0, 3).join(' · ')}
        </p>
      )}
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
              {s.note
                ? <p className="mt-1 text-[11px] text-amber-700">{s.note}</p>
                : <ul className="mt-1.5 grid sm:grid-cols-2 gap-1.5">{s.candidates.map((c) => <MenuChip key={c.id} it={c} />)}</ul>}
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
"""
s = s.replace(anchor, components + "\n" + anchor, 1)

# 3) 상태 + 로딩
old_state = """  const [tab, setTab] = useState('scan')
  const [area, setArea] = useState('all')"""
new_state = """  const [tab, setTab] = useState('scan')
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
  }"""
assert old_state in s
s = s.replace(old_state, new_state)

# 탭 전환 시 로드
old_tabsel = "<Tabs tab={tab} onChange={setTab} counts={{ priority: d.priorities?.length || 0 }} />"
new_tabsel = ("<Tabs tab={tab} onChange={(t) => { setTab(t); if (t === 'action') loadAction() }} "
              "counts={{ priority: d.priorities?.length || 0, action: act?.plans?.length ?? null }} />")
assert old_tabsel in s
s = s.replace(old_tabsel, new_tabsel)

# 4) 개선안 탭 본문 — priority 탭 블록 뒤에 넣는다
old_after = """          {tab === 'scan' && (
          <>"""
new_after = """          {tab === 'action' && (
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
          <>"""
assert old_after in s
s = s.replace(old_after, new_after, 1)

io.open(p, 'w', encoding='utf-8').write(s)
print('FacilityPage.jsx 패치 완료:', len(s), 'bytes')

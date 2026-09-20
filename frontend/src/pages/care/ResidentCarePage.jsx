import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { Card, LevelPill, ScoreBar, SOLUTION_STATUS, TRANSITION, TypeBadge, errMsg, fmtDate } from '../../components/care/CareUI'
import Avatar from '../../components/care/Avatar'
import ResidentProfileTab from './ResidentProfileTab'
import ResidentHistoryTab from './ResidentHistoryTab'

const INDICATORS = [
  ['mna_sf', 'MNA-SF', '점 / 14', (v) => (v <= 7 ? 'bad' : v <= 11 ? 'warn' : 'ok')],
  ['bmi', 'BMI', 'kg/m²', (v) => (v < 18.5 ? 'bad' : 'ok'), 1],
  ['kmbi_pct', 'K-MBI', '%', (v) => (v < 40 ? 'bad' : v < 70 ? 'warn' : 'ok')],
  ['mmse', 'K-MMSE-2', '점 / 30'],
  ['gds', 'GDS-SF', '점 / 15', (v) => (v >= 8 ? 'bad' : v >= 5 ? 'warn' : 'ok'), 1],
  ['intake_total', '전체 섭취율', '%', (v) => (v < 50 ? 'bad' : v < 75 ? 'warn' : 'ok')],
  ['intake_main', '주찬 섭취율', '%', (v) => (v < 50 ? 'bad' : v < 75 ? 'warn' : 'ok')],
  ['sat_overall', '급식 만족', '/ 5', (v) => (v <= 2.5 ? 'warn' : 'ok'), 1],
]
const TONE = { bad: 'text-rose-600', warn: 'text-amber-600', ok: 'text-gray-900' }
const TEXTURE = ['일반식', '다진식', '갈은식', '유동식']
const PROVIDERS = [['', '기본 설정'], ['openai', 'OpenAI'], ['anthropic', 'Claude'], ['rules', '규칙 기반']]

function Indicator({ f, k, label, unit, tone, digits = 0 }) {
  const v = f?.[k]
  const t = v != null && tone ? TONE[tone(v)] : 'text-gray-900'
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2.5">
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${t}`}>{v == null ? '–' : Number(v).toFixed(digits)}<span className="ml-1 text-[11px] font-normal text-gray-400">{unit}</span></p>
    </div>
  )
}

function SurveyCheck({ elderlyId }) {
  const [c, setC] = useState(null)
  const [state, setState] = useState('idle')
  const run = async () => {
    setState('loading')
    try {
      const { data } = await api.get(`/care/residents/${elderlyId}/survey-check`)
      setC(data); setState('done')
    } catch { setState('error') }
  }
  const Row = ({ label, r }) => (
    <div className="py-2 border-b border-gray-50 last:border-0">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm text-gray-700">{label}</span>
        <span className={`text-xs font-semibold ${!r.exists ? 'text-rose-600' : r.missing.length ? 'text-amber-600' : 'text-emerald-600'}`}>
          {!r.exists ? '미작성' : r.missing.length ? `${r.missing.length}개 항목 비어 있음` : '모두 입력됨'}
        </span>
      </div>
      {r.missing.length > 0 && <p className="mt-1 text-[11px] text-gray-500">{r.missing.join(' · ')}</p>}
      {r.groups?.length > 0 && (
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          {r.groups.map((g) => (
            <span key={g.name} className={`text-[11px] rounded px-2 py-1 ${g.filled === 0 ? 'bg-rose-50 text-rose-700' : g.filled < g.total ? 'bg-amber-50 text-amber-700' : 'bg-slate-50 text-gray-600'}`}>
              {g.name} {g.filled}/{g.total}
            </span>
          ))}
        </div>
      )}
    </div>
  )
  return (
    <Card title="설문 데이터 점검" right={<button onClick={run} className="text-xs font-semibold text-navy-600 hover:underline">{state === 'loading' ? '확인 중…' : '확인'}</button>}>
      {state === 'idle' && <p className="text-xs text-gray-500">리포트에 <b>–</b> 또는 <b>미실시</b>로 보이는 항목이 있으면 여기서 설문 원본에 값이 들어 있는지 확인하세요.</p>}
      {state === 'error' && <p className="text-xs text-red-600">확인에 실패했습니다.</p>}
      {c && (
        <div>
          <Row label="기초 조사표" r={c.basic} />
          <Row label="영양(섭취) 조사표" r={c.nutrition} />
          <Row label="만족도 조사표" r={c.satisfaction} />
          {c.assessment?.stale && (
            <p className="mt-3 text-xs rounded-lg bg-amber-50 text-amber-800 px-3 py-2">
              이 어르신의 평가는 예전 버전에서 계산된 것이라 키·혈압·학력 등 최근에 추가된 항목이 비어 있습니다. 위의 <b>이 어르신 재평가</b> 버튼을 누르면 채워집니다.
            </p>
          )}
          {c.assessment && !c.assessment.stale && (
            <p className="mt-3 text-[11px] text-gray-400">최근 평가 {fmtDate(c.assessment.created_at)} · 모델 {c.assessment.model_version}</p>
          )}
        </div>
      )}
    </Card>
  )
}

const RESIDENT_TABS = [
  { key: 'profile', label: 'PROFILE', ko: '어르신 정보' },
  { key: 'care', label: 'CARE', ko: '평가 · 솔루션' },
  { key: 'history', label: 'HISTORY', ko: '타임라인' },
]

function ResidentTabs({ active, onChange }) {
  return (
    <div className="mb-5 flex gap-1.5 rounded-2xl bg-white ring-1 ring-gray-200 p-1.5">
      {RESIDENT_TABS.map((t) => {
        const on = t.key === active
        return (
          <button key={t.key} type="button" onClick={() => onChange(t.key)}
            className={`flex-1 rounded-xl px-3 py-2 text-center transition ${on ? 'bg-navy-900 text-white shadow-sm' : 'text-navy-900/70 hover:bg-navy-50'}`}>
            <span className="block text-[13px] font-extrabold tracking-wide">{t.label}</span>
            <span className={`block text-[10px] ${on ? 'text-navy-100/80' : 'text-gray-400'}`}>{t.ko}</span>
          </button>
        )
      })}
    </div>
  )
}

function NutritionCard({ n }) {
  if (!n?.targets?.length) return null
  const tone = (b) => (b === 'bad' ? 'bg-rose-500' : b === 'warn' ? 'bg-amber-500' : 'bg-emerald-500')
  const txt = (b) => (b === 'bad' ? 'text-rose-600' : b === 'warn' ? 'text-amber-700' : 'text-emerald-700')
  const show = n.targets.filter((t) => ['energy', 'protein', 'fiber', 'ca', 'na', 'k'].includes(t.key))
  return (
    <Card title="섭취 영양소" right={<span className="text-xs text-gray-400">하루 평균 · {n.n_days || 0}일</span>}>
      {n.partial && (
        <p className="mb-3 text-[11px] rounded-lg bg-amber-50 text-amber-900 px-3 py-2">
          15끼 중 {n.n_meals}끼만 조사돼, 기록된 끼니를 하루 세 끼로 환산했습니다.
        </p>
      )}
      <div className="space-y-2.5">
        {show.map((t) => (
          <div key={t.key} className="flex items-center gap-2.5">
            <span className="w-16 shrink-0 text-xs text-gray-600">{t.label}</span>
            <div className="relative h-2.5 flex-1 min-w-0 rounded-full bg-gray-100">
              <div className={`absolute inset-y-0 left-0 rounded-full ${tone(t.band)}`}
                style={{ width: `${Math.max(2, Math.min(100, t.pct))}%` }} />
            </div>
            <span className="w-28 shrink-0 text-right text-[11px] tabular-nums text-gray-500">
              <b className="text-gray-900">{t.value}</b> / {t.target} {t.unit}
            </span>
            <span className={`w-10 shrink-0 text-right text-xs font-bold tabular-nums ${txt(t.band)}`}>{t.pct}%</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-gray-400">
        식단표 · 배식량 · 목측법 잔반으로 계산한 실제 섭취량입니다. 기준은 2020 한국인 영양소 섭취기준(65세 이상), 나트륨은 이하 관리 기준입니다.
      </p>
      {n.meals?.length > 0 && (
        <div className="mt-4 grid grid-cols-3 gap-2">
          {n.meals.map((m) => (
            <div key={m.meal} className="rounded-xl bg-slate-50 px-3 py-2 text-center">
              <p className="text-[11px] text-gray-500">{m.meal}</p>
              <p className="text-sm font-bold tabular-nums text-gray-900">{Math.round(m.energy || 0)}<span className="text-[10px] font-normal text-gray-400"> kcal</span></p>
              <p className="text-[10px] text-gray-500 tabular-nums">단백질 {Number(m.protein || 0).toFixed(1)}g</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

/* 편집창(textarea) 안에서는 위첨자를 그릴 수 없다.
   그래서 본문에 박힌 [1] 같은 근거 표기를 떼어내 배지로 따로 보여주고,
   저장할 때 다시 문장 끝에 붙여 근거가 유실되지 않게 한다. */
const CITE_RE = /\s*\[G?(\d+)\]/g

function splitCites(text) {
  const cites = []
  const body = String(text || '').replace(CITE_RE, (_m, n) => { cites.push(Number(n)); return '' }).trim()
  return { body, cites: [...new Set(cites)].sort((a, b) => a - b) }
}

function joinCites(body, cites) {
  const clean = String(body || '').replace(CITE_RE, '').trim()
  return cites?.length ? `${clean} ${cites.map((n) => `[${n}]`).join('')}` : clean
}

function CiteBadges({ cites }) {
  if (!cites?.length) return null
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <span className="text-[10px] text-gray-400">근거</span>
      {cites.map((n) => (
        <span key={n} className="inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded bg-navy-100 text-navy-700 text-[10px] font-bold tabular-nums">{n}</span>
      ))}
    </div>
  )
}

function ListEditor({ items, onChange, placeholder }) {
  return (
    <div className="space-y-2">
      {items.map((x, i) => {
        const { body, cites } = splitCites(x)
        return (
          <div key={i} className="flex gap-2">
            <div className="flex-1 min-w-0">
              <textarea rows={2} className="form-input text-sm" value={body}
                onChange={(e) => onChange(items.map((y, j) => (j === i ? joinCites(e.target.value, cites) : y)))} />
              <CiteBadges cites={cites} />
            </div>
            <button type="button" onClick={() => onChange(items.filter((_, j) => j !== i))} className="text-gray-300 hover:text-red-500 text-lg leading-none">×</button>
          </div>
        )
      })}
      <button type="button" onClick={() => onChange([...items, ''])} className="text-xs text-blue-600 hover:underline">+ {placeholder}</button>
    </div>
  )
}

function KakaoPreview({ r }) {
  return (
    <div className="rounded-2xl bg-[#b2c7da] p-3">
      <div className="text-[11px] text-slate-700 mb-1.5">
        {r.guardian} · {r.phone} · {r.mode === 'dry_run' ? '테스트 모드(미발송)' : r.status === 'sent' ? '발송 접수됨' : '발송 실패'}
        {r.status === 'failed' && r.error && <span className="ml-1 text-red-700">({r.error})</span>}
      </div>
      <div className="max-w-xs rounded-xl bg-white overflow-hidden shadow-sm">
        <div className={`px-3 py-1.5 text-xs font-bold ${r.mode === 'sms' ? 'bg-emerald-100 text-emerald-900' : 'bg-[#fee500] text-gray-900'}`}>{r.mode === 'sms' ? '문자(LMS)' : '알림톡 도착'}</div>
        <pre className="whitespace-pre-wrap font-sans text-[13px] leading-relaxed text-gray-800 px-3 py-3">{r.text}</pre>
        {r.mode !== 'sms' && <a href={r.report_url} target="_blank" rel="noreferrer" className="block border-t border-gray-100 text-center text-sm py-2 text-gray-700 hover:bg-gray-50">{r.button?.name || '돌봄 리포트 보기'}</a>}
      </div>
    </div>
  )
}

export default function ResidentCarePage() {
  const { elderlyId } = useParams()
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState('')
  const [tab, setTab] = useState('profile')
  const [provider, setProvider] = useState('')
  const [draft, setDraft] = useState(null)
  const [msg, setMsg] = useState(null)
  const [sendResult, setSendResult] = useState(null)
  const [gForm, setGForm] = useState({ name: '', relation: '', phone: '', consent_health_info: false })
  const [aForm, setAForm] = useState({ action: '', status: 'done', outcome_note: '' })

  const load = () => api.get(`/care/residents/${elderlyId}`).then((r) => {
    setD(r.data)
    const s = r.data.solutions?.[0]
    setDraft(s ? { id: s.id, summary: s.content.summary || '', staff_actions: s.content.staff_actions || [],
      meal_guidance: s.content.meal_guidance || [], monitoring: s.content.monitoring || [],
      cautions: s.content.cautions || [], references: s.content.references || [],
      guardian_message: s.guardian_message } : null)
  }).catch((e) => setErr(errMsg(e)))
  useEffect(() => { load() }, [elderlyId])

  const act = async (key, fn, okText) => {
    setBusy(key); setMsg(null)
    try {
      const out = await fn()
      if (okText) setMsg({ kind: 'ok', text: okText(out) })
      await load()
      return out
    } catch (e) {
      setMsg({ kind: 'error', text: errMsg(e) })
    } finally {
      setBusy('')
    }
  }

  if (err) return <CareLayout title="어르신"><p className="surface p-6 text-red-700">{err} <Link to="/care" className="text-navy-600 ml-2 underline">목록으로</Link></p></CareLayout>
  if (!d) return <CareLayout title="어르신"><div className="surface p-12 text-center text-muted">불러오는 중…</div></CareLayout>

  const a = d.assessments[0]
  const f = a?.features || {}
  const sol = d.solutions[0]
  const tr = a?.transition
  const trStyle = tr?.kind && TRANSITION[tr.kind]
  const consented = d.guardians.filter((g) => g.consent_health_info)

  const reassess = () => act('assess', () => api.post('/care/assess', { elderly_ids: [elderlyId], force: true }, { timeout: 120000 }),
    () => '최신 설문 기준으로 다시 평가했습니다.')
  const generate = () => act('gen', () => api.post(`/care/residents/${elderlyId}/solutions`, provider ? { provider } : {}, { timeout: 120000 }),
    (r) => `솔루션 초안을 만들었습니다 (${r.data.generator}). 검토 후 승인하세요.`)
  const save = () => act('save', () => api.put(`/care/solutions/${draft.id}`, {
    content: { summary: draft.summary, staff_actions: draft.staff_actions, meal_guidance: draft.meal_guidance.filter(Boolean),
      monitoring: draft.monitoring.filter(Boolean), cautions: draft.cautions.filter(Boolean),
      references: draft.references || [] },
    guardian_message: draft.guardian_message,
  }), (r) => (r.data.warnings?.length ? `저장했습니다. 확인 필요: ${r.data.warnings.join(', ')}` : '저장했습니다. 수정 후에는 다시 승인해야 합니다.'))
  const approve = () => act('approve', () => api.post(`/care/solutions/${draft.id}/approve`), () => '승인했습니다. 보호자에게 보낼 수 있습니다.')
  const reject = () => act('reject', () => api.post(`/care/solutions/${draft.id}/reject`), () => '반려했습니다.')
  const send = async () => {
    const out = await act('send', () => api.post(`/care/solutions/${draft.id}/send`, {}),
      (r) => `${r.data.results.length}명에게 ${r.data.mode === 'dry_run' ? '테스트 발송(미리보기)' : '발송'}했습니다.` + (r.data.skipped_no_consent.length ? ` 동의 없음 제외: ${r.data.skipped_no_consent.join(', ')}` : ''))
    if (out) setSendResult(out.data)
  }
  const addGuardian = (e) => {
    e.preventDefault()
    act('g', () => api.post(`/care/residents/${elderlyId}/guardians`, gForm), () => '보호자를 등록했습니다.')
      .then((r) => r && setGForm({ name: '', relation: '', phone: '', consent_health_info: false }))
  }
  const toggleConsent = (g) => act('g', () => api.put(`/care/guardians/${g.id}`, { name: g.name, relation: g.relation, phone: g.phone, consent_health_info: !g.consent_health_info }))
  const removeGuardian = (g) => window.confirm(`${g.name} 보호자를 삭제할까요?`) && act('g', () => api.delete(`/care/guardians/${g.id}`))
  const addAction = (e) => {
    e.preventDefault()
    act('act', () => api.post(`/care/residents/${elderlyId}/actions`, { ...aForm, solution_id: sol?.id }), () => '수행 기록을 저장했습니다.')
      .then((r) => r && setAForm({ action: '', status: 'done', outcome_note: '' }))
  }
  const editable = draft && sol && sol.status !== 'sent'

  return (
    <CareLayout
      title={d.resident.display_name}
      subtitle={a ? `평가 ${fmtDate(a.created_at)} · 모델 ${a.model_version}` : '아직 평가되지 않았습니다'}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {a && <TypeBadge code={a.type_code} name={a.type_name} size="lg" />}
          {a && <LevelPill level={a.priority_level} />}
          {trStyle && <span className={`badge ${trStyle.cls}`}>{trStyle.label} {tr.prev_type} → {a.type_code}</span>}
          {a?.is_borderline && <span className="badge bg-violet-50 text-violet-700">경계 사례</span>}
        </div>
      }
    >
      <div className="mb-4 flex items-center justify-between gap-3">
        <Link to="/care" className="text-xs font-semibold text-navy-600 hover:underline">← 진단 목록</Link>
        <div className="flex items-center gap-2">
          <button onClick={reassess} disabled={busy === 'assess'} className="btn-secondary text-xs py-1.5">
            {busy === 'assess' ? '재평가 중…' : '이 어르신 재평가'}
          </button>
          <Link to={`/care/residents/${elderlyId}/report`} className="btn-secondary text-xs py-1.5">상세 리포트 보기</Link>
        </div>
      </div>

      {msg && (
        <p className={`mb-4 text-sm rounded-xl px-4 py-3 ${msg.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-navy-50 text-navy-800'}`}>{msg.text}</p>
      )}

      <div className="mb-4 flex items-center gap-3">
        <Avatar name={d.resident.display_name} id={elderlyId} size="md" />
        <div className="min-w-0">
          <p className="text-base font-extrabold text-gray-900 leading-tight">{d.resident.display_name}</p>
          <p className="text-xs text-gray-400">{elderlyId}{a ? ` · 최근 평가 ${fmtDate(a.created_at)}` : ''}</p>
        </div>
      </div>

      <ResidentTabs active={tab} onChange={setTab} />

      {tab === 'profile' && <ResidentProfileTab elderlyId={elderlyId} residentName={d.resident.display_name} />}
      {tab === 'history' && <ResidentHistoryTab elderlyId={elderlyId} />}

      <div className={`grid lg:grid-cols-5 gap-5 ${tab === 'care' ? '' : 'hidden'}`}>
        {/* 왼쪽: 평가 */}
        <div className="lg:col-span-2 space-y-5">
          <SurveyCheck elderlyId={elderlyId} />
          {!a ? (
            <Card title="평가 결과"><p className="text-sm text-gray-500">아직 평가되지 않았습니다. 목록 화면에서 평가를 실행하세요.</p></Card>
          ) : (
            <>
              <Card title="돌봄 우선순위" right={<span className="text-xs text-gray-400">0–100</span>}>
                <ScoreBar score={a.priority_score} level={a.priority_level} />
                <ul className="mt-4 space-y-2">
                  {a.priority_factors.map((x) => (
                    <li key={x.code} className="flex items-start justify-between gap-3 text-sm">
                      <span className="text-gray-700">
                        {x.kind === 'trend' && <span className="mr-1 text-[10px] rounded bg-rose-50 text-rose-600 px-1">변화</span>}
                        {x.label}{x.value != null && x.value !== 1 && typeof x.value !== 'boolean' ? <span className="text-gray-400"> · {x.value}</span> : null}
                      </span>
                      <span className={`shrink-0 text-xs font-semibold tabular-nums ${x.points ? 'text-gray-900' : 'text-gray-300'}`}>+{x.points}</span>
                    </li>
                  ))}
                </ul>
              </Card>

              <Card title="유형 판정 근거">
                {d.type_info?.description && <p className="text-sm text-gray-700 mb-3">{d.type_info.description}</p>}
                <p className="text-xs text-gray-500 mb-2">시설 전체 평균과 비교해 두드러진 지표</p>
                <ul className="space-y-1.5">
                  {(tr?.deviations || []).map((x) => (
                    <li key={x.var} className="flex items-center gap-2 text-sm">
                      <span className="w-32 shrink-0 truncate text-gray-600">{x.label}</span>
                      <div className="relative h-2 flex-1 bg-gray-100 rounded-full">
                        <div className="absolute top-0 h-2 w-px bg-gray-300 left-1/2" />
                        <div className={`absolute top-0 h-2 rounded-full ${x.z > 0 ? 'bg-blue-400 left-1/2' : 'bg-orange-400 right-1/2'}`}
                          style={{ width: `${Math.min(50, Math.abs(x.z) * 20)}%` }} />
                      </div>
                      <span className="w-12 text-right text-xs tabular-nums text-gray-500">{x.z > 0 ? '+' : ''}{x.z}</span>
                    </li>
                  ))}
                </ul>
                {a.is_borderline && <p className="mt-3 text-xs rounded-lg bg-violet-50 text-violet-700 px-3 py-2">두 번째로 가까운 유형({tr?.second_type})과 거리 차이가 작습니다. 담당자 판단으로 확인해 주세요.</p>}
                {a.imputed_vars?.length > 0 && <p className="mt-2 text-xs text-gray-400">추정값 사용 지표: {a.imputed_vars.join(', ')}</p>}
              </Card>

              <Card title="주요 지표">
                <div className="grid grid-cols-2 gap-2">
                  {INDICATORS.map(([k, label, unit, tone, digits]) => <Indicator key={k} f={f} k={k} label={label} unit={unit} tone={tone} digits={digits} />)}
                </div>
                <div className="mt-3 flex flex-wrap gap-1.5 text-xs">
                  {f.chewing_difficulty === 1 && <span className="rounded bg-rose-50 text-rose-700 px-2 py-0.5">씹기 어려움</span>}
                  {f.swallowing_difficulty === 1 && <span className="rounded bg-rose-50 text-rose-700 px-2 py-0.5">삼킴 어려움</span>}
                  {f.texture_level != null && <span className="rounded bg-gray-100 text-gray-700 px-2 py-0.5">{TEXTURE[f.texture_level] || '식사형태 ?'}</span>}
                  {f.dx_dementia === 1 && <span className="rounded bg-gray-100 text-gray-700 px-2 py-0.5">치매</span>}
                  {f.dx_diabetes === 1 && <span className="rounded bg-gray-100 text-gray-700 px-2 py-0.5">당뇨</span>}
                  {f.dx_hypertension === 1 && <span className="rounded bg-gray-100 text-gray-700 px-2 py-0.5">고혈압</span>}
                  {f.pref_seafood === 1 && <span className="rounded bg-sky-50 text-sky-700 px-2 py-0.5">생선 선호</span>}
                </div>
              </Card>

              <NutritionCard n={d.nutrition} />

              <Card title="평가 이력">
                <table className="w-full text-sm">
                  <tbody>
                    {d.assessments.map((h) => (
                      <tr key={h.id} className="border-b border-gray-50 last:border-0">
                        <td className="py-2 text-xs text-gray-500">{fmtDate(h.created_at)}</td>
                        <td className="py-2"><TypeBadge code={h.type_code} /></td>
                        <td className="py-2 text-right tabular-nums font-semibold">{Math.round(h.priority_score)}</td>
                        <td className="py-2 pl-2 text-right text-[11px] tabular-nums text-gray-500">
                          {h.features?.nutrition?.avg_day?.energy != null ? `${Math.round(h.features.nutrition.avg_day.energy)}kcal` : ''}
                        </td>
                        <td className="py-2 pl-2 text-right text-[11px] text-gray-400">{TRANSITION[h.transition?.kind]?.label || ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </>
          )}
        </div>

        {/* 오른쪽: 솔루션 · 보호자 · 기록 */}
        <div className="lg:col-span-3 space-y-5">
          <Card title="돌봄 솔루션" right={sol && <span className={`text-xs rounded-full px-2.5 py-0.5 ${SOLUTION_STATUS[sol.status]?.cls}`}>{SOLUTION_STATUS[sol.status]?.label}</span>}>
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <select value={provider} onChange={(e) => setProvider(e.target.value)} className="form-select w-auto text-sm">
                {PROVIDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
              <button onClick={generate} disabled={!a || busy === 'gen'} className="btn-secondary text-sm">
                {busy === 'gen' ? '생성 중…' : sol ? '새 초안 만들기' : '솔루션 초안 만들기'}
              </button>
              {sol && <span className="text-xs text-gray-400">{sol.generator} · {fmtDate(sol.created_at)}</span>}
            </div>

            {sol?.guardrail_flags?.length > 0 && (
              <div className="mb-4 rounded-xl bg-amber-50 border border-amber-200 px-4 py-3">
                <p className="text-xs font-semibold text-amber-800 mb-1">자동 검증에서 수정된 부분</p>
                <ul className="list-disc pl-4 text-xs text-amber-800 space-y-0.5">{sol.guardrail_flags.map((x, i) => <li key={i}>{x.detail}</li>)}</ul>
              </div>
            )}

            {draft && (
              <div className="space-y-5">
                <div>
                  <label className="form-label">담당자용 요약</label>
                  <textarea rows={2} className="form-input" value={splitCites(draft.summary).body} disabled={!editable}
                    onChange={(e) => setDraft({ ...draft, summary: joinCites(e.target.value, splitCites(draft.summary).cites) })} />
                </div>
                <div>
                  <label className="form-label">돌봄 조치</label>
                  <div className="space-y-2">
                    {draft.staff_actions.map((x, i) => (
                      <div key={i} className="rounded-xl border border-gray-200 p-3">
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-xs font-semibold text-blue-700">{x.category}</span>
                          <span className="text-[10px] text-gray-400">{x.rule_id}</span>
                        </div>
                        <textarea rows={2} className="form-input text-sm" value={splitCites(x.action).body} disabled={!editable}
                          onChange={(e) => setDraft({ ...draft, staff_actions: draft.staff_actions.map((y, j) => (j === i ? { ...y, action: joinCites(e.target.value, splitCites(x.action).cites) } : y)) })} />
                        <CiteBadges cites={[...new Set([...splitCites(x.action).cites, ...splitCites(x.why).cites])].sort((a, b) => a - b)} />
                        {x.why && <p className="mt-1 text-xs text-gray-500">이유: {splitCites(x.why).body}</p>}
                      </div>
                    ))}
                  </div>
                </div>
                <div className="grid md:grid-cols-2 gap-4">
                  <div>
                    <label className="form-label">식사 지침</label>
                    {editable ? <ListEditor items={draft.meal_guidance} onChange={(v) => setDraft({ ...draft, meal_guidance: v })} placeholder="지침 추가" />
                      : <ul className="list-disc pl-4 text-sm text-gray-700 space-y-1">{draft.meal_guidance.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                  </div>
                  <div>
                    <label className="form-label">관찰 · 재평가</label>
                    {editable ? <ListEditor items={draft.monitoring} onChange={(v) => setDraft({ ...draft, monitoring: v })} placeholder="항목 추가" />
                      : <ul className="list-disc pl-4 text-sm text-gray-700 space-y-1">{draft.monitoring.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                  </div>
                </div>
                <div>
                  <div className="flex items-end justify-between">
                    <label className="form-label">보호자 안내 문장</label>
                    <span className={`text-xs ${draft.guardian_message.length > 350 ? 'text-red-600' : 'text-gray-400'}`}>{draft.guardian_message.length}/350</span>
                  </div>
                  <textarea rows={4} className="form-input" value={draft.guardian_message} disabled={!editable}
                    onChange={(e) => setDraft({ ...draft, guardian_message: e.target.value })} />
                  <p className="mt-1 text-xs text-gray-400">점수·척도명·약 이름은 쓰지 마세요. 보호자 리포트 화면에 그대로 보입니다.</p>
                </div>
                {draft.references?.length > 0 && (
                  <div className="rounded-xl bg-navy-50/60 px-4 py-3">
                    <p className="text-xs font-bold text-navy-900 mb-1.5">근거 문헌</p>
                    <ol className="space-y-1">
                      {draft.references.map((x) => (
                        <li key={x.tag} className="flex gap-2 text-xs leading-5">
                          <span className="font-bold text-navy-500 shrink-0 tabular-nums">{String(x.tag).replace('G', '')}</span>
                          <span className="min-w-0">
                            <b className="font-semibold text-navy-900">{x.locator || x.title}</b>
                            <span className="ml-1.5 text-gray-400">{x.short || x.citation}</span>
                            {x.url && <a href={x.url} target="_blank" rel="noreferrer" className="ml-1.5 text-navy-500 underline">원문</a>}
                          </span>
                        </li>
                      ))}
                    </ol>
                    <p className="mt-2 text-[11px] text-gray-400">각 조치·지침 아래 '근거' 배지의 번호가 이 목록을 가리킵니다. 상세 리포트에서는 문장 끝 위첨자로 표시됩니다.</p>
                  </div>
                )}
                {editable && (
                  <div className="flex flex-wrap gap-2 pt-1">
                    <button onClick={save} disabled={!!busy} className="btn-secondary text-sm">{busy === 'save' ? '저장 중…' : '수정 저장'}</button>
                    <button onClick={approve} disabled={!!busy || sol.status === 'approved'} className="btn-primary text-sm">담당자 승인</button>
                    <button onClick={reject} disabled={!!busy || sol.status === 'rejected'} className="btn text-sm text-gray-500 hover:text-red-600">반려</button>
                  </div>
                )}
              </div>
            )}
            {!draft && <p className="text-sm text-gray-500">평가 결과와 규칙 근거를 바탕으로 초안을 만든 뒤, 담당자가 검토·승인합니다.</p>}
          </Card>

          <Card title="보호자 알림" right={<span className="text-xs text-gray-400">카카오 알림톡 · 문자</span>}>
            <div className="flex flex-wrap items-center gap-3">
              <button onClick={send} disabled={!sol || !['approved', 'sent'].includes(sol.status) || consented.length === 0 || busy === 'send'} className="btn-primary text-sm">
                {busy === 'send' ? '발송 중…' : `동의한 보호자 ${consented.length}명에게 보내기`}
              </button>
              <p className="text-xs text-gray-500">
                {!sol ? '솔루션을 먼저 만드세요.' : !['approved', 'sent'].includes(sol.status) ? '승인된 솔루션만 보낼 수 있습니다.' : consented.length === 0 ? '건강정보 수신에 동의한 보호자가 없습니다.' : '승인된 내용으로 알림톡과 리포트 링크를 보냅니다.'}
              </p>
            </div>
            {sendResult && <div className="mt-4 grid md:grid-cols-2 gap-3">{sendResult.results.map((r, i) => <KakaoPreview key={i} r={r} />)}</div>}
            {d.notifications.length > 0 && (
              <div className="mt-4">
                <p className="text-xs font-semibold text-gray-500 mb-2">발송 이력</p>
                <ul className="text-xs text-gray-600 space-y-1">
                  {d.notifications.map((n) => (
                    <li key={n.id} className="flex justify-between gap-2">
                      <span>{fmtDate(n.created_at)} · {n.mode === 'dry_run' ? '테스트' : n.mode === 'sms' ? '문자' : '알림톡'}</span>
                      <span className={n.status === 'failed' ? 'text-red-600' : 'text-gray-500'}>{n.status === 'previewed' ? '미리보기' : n.status === 'sent' ? '발송' : '실패'}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Card>

          <Card title="보호자">
            <ul className="divide-y divide-gray-100 mb-4">
              {d.guardians.length === 0 && <li className="py-2 text-sm text-gray-400">등록된 보호자가 없습니다.</li>}
              {d.guardians.map((g) => (
                <li key={g.id} className="py-2.5 flex flex-wrap items-center justify-between gap-2 text-sm">
                  <span className="text-gray-800 font-medium">{g.name} <span className="text-gray-400 font-normal">{g.relation} · {g.phone_masked}</span></span>
                  <span className="flex items-center gap-3">
                    <button onClick={() => toggleConsent(g)} className={`text-xs rounded-full px-2 py-0.5 ${g.consent_health_info ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-500'}`}>
                      {g.consent_health_info ? '수신 동의' : '동의 없음'}
                    </button>
                    <button onClick={() => removeGuardian(g)} className="text-xs text-gray-400 hover:text-red-600">삭제</button>
                  </span>
                </li>
              ))}
            </ul>
            <form onSubmit={addGuardian} className="grid sm:grid-cols-3 gap-2">
              <input className="form-input" placeholder="이름" value={gForm.name} onChange={(e) => setGForm({ ...gForm, name: e.target.value })} required />
              <input className="form-input" placeholder="관계 (예: 자녀)" value={gForm.relation} onChange={(e) => setGForm({ ...gForm, relation: e.target.value })} />
              <input className="form-input" placeholder="휴대폰 010-0000-0000" value={gForm.phone} onChange={(e) => setGForm({ ...gForm, phone: e.target.value })} required inputMode="tel" />
              <label className="sm:col-span-2 flex items-start gap-2 text-xs text-gray-600">
                <input type="checkbox" className="mt-0.5" checked={gForm.consent_health_info} onChange={(e) => setGForm({ ...gForm, consent_health_info: e.target.checked })} />
                어르신(또는 법정대리인)과 보호자에게서 건강정보 제공 및 알림 수신 동의를 받았습니다.
              </label>
              <button className="btn-secondary text-sm" disabled={busy === 'g'}>보호자 등록</button>
            </form>
          </Card>

          <Card title="돌봄 수행 기록" right={<span className="text-xs text-gray-400">모델 고도화용 결과 데이터</span>}>
            <form onSubmit={addAction} className="grid sm:grid-cols-6 gap-2 mb-4">
              <input list="action-options" className="form-input sm:col-span-3" placeholder="수행한 조치" value={aForm.action} onChange={(e) => setAForm({ ...aForm, action: e.target.value })} required />
              <datalist id="action-options">{(draft?.staff_actions || []).map((x, i) => <option key={i} value={x.action} />)}</datalist>
              <select className="form-select sm:col-span-1" value={aForm.status} onChange={(e) => setAForm({ ...aForm, status: e.target.value })}>
                <option value="done">수행</option><option value="planned">예정</option><option value="skipped">미수행</option>
              </select>
              <input className="form-input sm:col-span-2" placeholder="결과 메모 (예: 사레 줄어듦)" value={aForm.outcome_note} onChange={(e) => setAForm({ ...aForm, outcome_note: e.target.value })} />
              <button className="btn-secondary text-sm sm:col-span-6 sm:justify-self-end" disabled={busy === 'act'}>기록 추가</button>
            </form>
            <ul className="space-y-2">
              {d.actions.length === 0 && <li className="text-sm text-gray-400">기록이 없습니다.</li>}
              {d.actions.map((x) => (
                <li key={x.id} className="text-sm border-l-2 border-blue-200 pl-3">
                  <div className="text-gray-800">{x.action}</div>
                  <div className="text-xs text-gray-400">{fmtDate(x.recorded_at)} · {{ done: '수행', planned: '예정', skipped: '미수행' }[x.status]}{x.outcome_note ? ` · ${x.outcome_note}` : ''}</div>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </CareLayout>
  )
}

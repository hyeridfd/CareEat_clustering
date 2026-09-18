import { useEffect, useState } from 'react'
import api from '../../lib/api'
import { Card, errMsg, fmtDate } from '../../components/care/CareUI'
import Avatar from '../../components/care/Avatar'

const TEXTURE = ['일반식', '다진식', '갈은식', '유동식']
const THICKENER = [['', '없음'], ['mild', '약간 걸쭉'], ['moderate', '중간'], ['extreme', '되직함']]
const LTC = ['1등급', '2등급', '3등급', '4등급', '5등급', '인지지원등급', '등급외', '미신청']
const DOSE_TIMES = ['아침', '점심', '저녁', '취침 전', '필요시']
const SEVERITY = {
  mild: ['경증', 'bg-amber-50 text-amber-700 border-amber-200'],
  moderate: ['중등', 'bg-orange-50 text-orange-700 border-orange-200'],
  severe: ['중증', 'bg-rose-50 text-rose-700 border-rose-200'],
}

function age(birth) {
  if (!birth) return null
  const b = new Date(birth)
  if (Number.isNaN(b.getTime())) return null
  const t = new Date()
  let a = t.getFullYear() - b.getFullYear()
  const m = t.getMonth() - b.getMonth()
  if (m < 0 || (m === 0 && t.getDate() < b.getDate())) a -= 1
  return a
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="form-label">{label}</span>
      {children}
    </label>
  )
}

function Empty({ text }) {
  return <p className="py-6 text-center text-sm text-muted">{text}</p>
}

export default function ResidentProfileTab({ elderlyId, residentName }) {
  const [d, setD] = useState(null)
  const [form, setForm] = useState(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState('')
  const [nc, setNc] = useState({ name: '', diagnosed_on: '', note: '' })
  const [nm, setNm] = useState({ name: '', dose: '', schedule: [], food_caution: '' })
  const [na, setNa] = useState({ allergen: '', severity: 'mild', reaction: '' })

  const load = () => api.get(`/ehr/residents/${elderlyId}/profile`)
    .then((r) => {
      setD(r.data)
      // 빈칸은 설문·보호자 등록 정보로 미리 채운다 (저장된 값이 있으면 그 값이 우선)
      const base = {
        birth_date: '', gender: '', admit_date: '', room: '', ltc_grade: '',
        guardian_name: '', guardian_relation: '', guardian_phone: '',
        texture_level: '', thickener: '', therapeutic_diet: '', notes: '',
        ...(r.data.survey_defaults || {}),
      }
      Object.entries(r.data.profile || {}).forEach(([k, v]) => {
        if (v !== null && v !== undefined && v !== '') base[k] = v
      })
      setForm(base)
    })
    .catch((e) => setErr(errMsg(e)))

  useEffect(() => { load() }, [elderlyId])

  const run = async (key, fn, ok) => {
    setBusy(key); setMsg('')
    try {
      await fn()
      await load()
      if (ok) setMsg(ok)
    } catch (e) {
      setMsg(errMsg(e))
    } finally {
      setBusy('')
    }
  }

  const saveProfile = () => run('profile', () => {
    const body = { ...form }
    delete body.elderly_id; delete body.nursing_home_id
    delete body.updated_at; delete body.created_at; delete body.updated_by
    body.texture_level = body.texture_level === '' ? null : Number(body.texture_level)
    Object.keys(body).forEach((k) => { if (body[k] === '') body[k] = null })
    return api.put(`/ehr/residents/${elderlyId}/profile`, body)
  }, '기본정보를 저장했습니다.')

  const importSurvey = () => run('import', () => api.post(`/ehr/residents/${elderlyId}/import-from-survey`),
    '기초조사표의 진단·복약을 가져왔습니다.')

  if (err) return <p className="surface p-6 text-red-700">{err}</p>
  if (!d || !form) return <div className="surface p-12 text-center text-muted">불러오는 중…</div>

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })
  const yrs = age(form.birth_date)

  return (
    <div className="space-y-5">
      {msg && <p className="text-sm rounded-xl bg-navy-50 text-navy-800 px-4 py-3">{msg}</p>}

      {/* ── 기본 인적사항 ───────────────────────── */}
      <Card
        title="기본 인적사항"
        right={
          <button onClick={saveProfile} disabled={busy === 'profile'} className="btn-primary text-xs py-1.5 disabled:opacity-50">
            {busy === 'profile' ? '저장 중…' : '저장'}
          </button>
        }
      >
        {(Object.keys(d.survey_defaults || {}).length > 0 || d.survey_birth_year) && !d.profile && (
          <p className="mb-4 text-[11px] rounded-xl bg-navy-50 text-navy-800 px-3 py-2">
            빈칸은 기초조사표와 등록된 보호자 정보에서 미리 채웠습니다. 확인 후 <b>저장</b>을 눌러 주세요.
          </p>
        )}
        <div className="flex flex-col sm:flex-row gap-6">
          <div className="flex sm:flex-col items-center gap-3 sm:w-28 shrink-0">
            <Avatar name={residentName} id={elderlyId} size="lg" />
            <div className="text-center">
              <p className="font-bold text-navy-900 leading-tight">{residentName}</p>
              <p className="text-[11px] text-muted mt-0.5 tabular-nums">{elderlyId}</p>
              {yrs != null && <p className="text-[11px] text-muted">만 {yrs}세</p>}
            </div>
          </div>

          <div className="flex-1 grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
            <Field label="생년월일">
              <input type="date" value={form.birth_date || ''} onChange={set('birth_date')} className="form-input" />
              {!form.birth_date && d.survey_birth_year && (
                <span className="mt-1 block text-[11px] text-muted">조사표 출생연도 {d.survey_birth_year}년</span>
              )}
            </Field>
            <Field label="성별">
              <select value={form.gender || ''} onChange={set('gender')} className="form-input">
                <option value="">선택</option><option value="female">여성</option><option value="male">남성</option>
              </select>
            </Field>
            <Field label="입소일">
              <input type="date" value={form.admit_date || ''} onChange={set('admit_date')} className="form-input" />
            </Field>
            <Field label="호실">
              <input value={form.room || ''} onChange={set('room')} placeholder="301호" className="form-input" />
            </Field>
            <Field label="장기요양등급">
              <select value={form.ltc_grade || ''} onChange={set('ltc_grade')} className="form-input">
                <option value="">선택</option>
                {LTC.map((g) => <option key={g} value={g}>{g}</option>)}
              </select>
            </Field>
            <Field label="보호자">
              <input value={form.guardian_name || ''} onChange={set('guardian_name')} placeholder="이름" className="form-input" />
            </Field>
            <Field label="보호자 관계">
              <input value={form.guardian_relation || ''} onChange={set('guardian_relation')} placeholder="자녀" className="form-input" />
            </Field>
            <Field label="보호자 연락처">
              <input value={form.guardian_phone || ''} onChange={set('guardian_phone')} placeholder="01012345678" className="form-input" />
            </Field>
          </div>
        </div>
      </Card>

      {/* ── 질병·진단 ───────────────────────────── */}
      <Card
        title="질병 · 진단"
        right={(d.survey_import?.conditions?.length > 0 || d.survey_import?.medications?.length > 0) && (
          <button onClick={importSurvey} disabled={busy === 'import'} className="btn-secondary text-xs py-1.5 disabled:opacity-50">
            {busy === 'import' ? '가져오는 중…'
              : `기초조사표에서 가져오기 (진단 ${d.survey_import.conditions.length} · 약 ${d.survey_import.medications.length})`}
          </button>
        )}
      >
        {d.survey_diagnoses?.length > 0 && (
          <div className="mb-4 rounded-xl bg-slate-50 px-4 py-3">
            <p className="text-[11px] font-semibold text-muted mb-1.5">설문에서 확인된 진단</p>
            <div className="flex flex-wrap gap-1.5">
              {d.survey_diagnoses.map((x) => (
                <span key={x} className="badge bg-white border border-navy-100 text-navy-700">{x}</span>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-muted">
              {d.survey_updated_at ? `${fmtDate(d.survey_updated_at)} 평가 기준` : ''} · 아래에서 직접 추가·수정할 수 있습니다.
            </p>
          </div>
        )}

        {d.conditions.length === 0 ? <Empty text="등록된 진단이 없습니다." /> : (
          <ul className="divide-y divide-slate-100 mb-4">
            {d.conditions.map((c) => (
              <li key={c.id} className="py-2.5 flex items-start gap-3">
                <div className="flex-1">
                  <p className="text-sm font-semibold text-navy-900">
                    {c.name}
                    {c.status === 'resolved' && <span className="ml-2 badge bg-slate-100 text-slate-500">종료</span>}
                  </p>
                  <p className="text-[11px] text-muted mt-0.5">
                    {c.diagnosed_on ? `진단 ${c.diagnosed_on}` : '진단일 미기재'}{c.note ? ` · ${c.note}` : ''}
                  </p>
                </div>
                <button onClick={() => run(`c${c.id}`, () => api.delete(`/ehr/residents/${elderlyId}/conditions/${c.id}`))}
                  className="text-[11px] text-muted hover:text-rose-600">삭제</button>
              </li>
            ))}
          </ul>
        )}

        <div className="grid sm:grid-cols-[1fr_140px_1fr_auto] gap-2">
          <input value={nc.name} onChange={(e) => setNc({ ...nc, name: e.target.value })}
            placeholder="진단명 (예: 치매)" className="form-input" />
          <input type="date" value={nc.diagnosed_on} onChange={(e) => setNc({ ...nc, diagnosed_on: e.target.value })} className="form-input" />
          <input value={nc.note} onChange={(e) => setNc({ ...nc, note: e.target.value })} placeholder="메모" className="form-input" />
          <button disabled={!nc.name.trim() || busy === 'nc'} className="btn-secondary disabled:opacity-40"
            onClick={() => run('nc', () => api.post(`/ehr/residents/${elderlyId}/conditions`,
              { ...nc, diagnosed_on: nc.diagnosed_on || null }).then(() => setNc({ name: '', diagnosed_on: '', note: '' })))}>
            추가
          </button>
        </div>
      </Card>

      {/* ── 복용 약물 ───────────────────────────── */}
      <Card title="복용 약물">
        {d.medications.length === 0 ? <Empty text="등록된 약물이 없습니다." /> : (
          <ul className="divide-y divide-slate-100 mb-4">
            {d.medications.map((m) => (
              <li key={m.id} className={`py-2.5 flex items-start gap-3 ${m.is_active ? '' : 'opacity-50'}`}>
                <div className="flex-1">
                  <p className="text-sm font-semibold text-navy-900">
                    {m.name}{m.dose ? <span className="ml-2 font-normal text-muted">{m.dose}</span> : null}
                    {!m.is_active && <span className="ml-2 badge bg-slate-100 text-slate-500">중단</span>}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {(m.schedule || []).map((s) => (
                      <span key={s} className="badge bg-navy-50 text-navy-700">{s}</span>
                    ))}
                  </div>
                  {m.food_caution && <p className="text-[11px] text-amber-700 mt-1">식사 주의: {m.food_caution}</p>}
                </div>
                <button onClick={() => run(`m${m.id}`, () => api.delete(`/ehr/residents/${elderlyId}/medications/${m.id}`))}
                  className="text-[11px] text-muted hover:text-rose-600">삭제</button>
              </li>
            ))}
          </ul>
        )}

        <div className="space-y-2">
          <div className="grid sm:grid-cols-[1fr_120px_1fr] gap-2">
            <input value={nm.name} onChange={(e) => setNm({ ...nm, name: e.target.value })}
              placeholder="약 이름" className="form-input" />
            <input value={nm.dose} onChange={(e) => setNm({ ...nm, dose: e.target.value })}
              placeholder="1정" className="form-input" />
            <input value={nm.food_caution} onChange={(e) => setNm({ ...nm, food_caution: e.target.value })}
              placeholder="식사 주의 (예: 자몽 피하기)" className="form-input" />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {DOSE_TIMES.map((t) => {
              const on = nm.schedule.includes(t)
              return (
                <button key={t} type="button"
                  onClick={() => setNm({ ...nm, schedule: on ? nm.schedule.filter((x) => x !== t) : [...nm.schedule, t] })}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition ${
                    on ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-navy-100 text-muted hover:border-navy-200'}`}>
                  {t}
                </button>
              )
            })}
            <button disabled={!nm.name.trim() || busy === 'nm'} className="btn-secondary ml-auto disabled:opacity-40"
              onClick={() => run('nm', () => api.post(`/ehr/residents/${elderlyId}/medications`, nm)
                .then(() => setNm({ name: '', dose: '', schedule: [], food_caution: '' })))}>
              추가
            </button>
          </div>
        </div>
      </Card>

      {/* ── 알레르기 · 식이제한 ──────────────────── */}
      <Card
        title="알레르기 · 식이제한"
        right={
          <button onClick={saveProfile} disabled={busy === 'profile'} className="btn-secondary text-xs py-1.5 disabled:opacity-50">
            식이 설정 저장
          </button>
        }
      >
        {d.allergies.length === 0 ? <Empty text="등록된 알레르기가 없습니다." /> : (
          <ul className="divide-y divide-slate-100 mb-4">
            {d.allergies.map((x) => {
              const [label, cls] = SEVERITY[x.severity] || SEVERITY.mild
              return (
                <li key={x.id} className="py-2.5 flex items-center gap-3">
                  <span className={`badge border ${cls}`}>{label}</span>
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-navy-900">{x.allergen}</p>
                    {x.reaction && <p className="text-[11px] text-muted mt-0.5">증상: {x.reaction}</p>}
                  </div>
                  <button onClick={() => run(`a${x.id}`, () => api.delete(`/ehr/residents/${elderlyId}/allergies/${x.id}`))}
                    className="text-[11px] text-muted hover:text-rose-600">삭제</button>
                </li>
              )
            })}
          </ul>
        )}

        <div className="grid sm:grid-cols-[1fr_130px_1fr_auto] gap-2 mb-5">
          <input value={na.allergen} onChange={(e) => setNa({ ...na, allergen: e.target.value })}
            placeholder="알레르기 원인 (예: 땅콩)" className="form-input" />
          <select value={na.severity} onChange={(e) => setNa({ ...na, severity: e.target.value })} className="form-input">
            <option value="mild">경증</option><option value="moderate">중등</option><option value="severe">중증</option>
          </select>
          <input value={na.reaction} onChange={(e) => setNa({ ...na, reaction: e.target.value })}
            placeholder="증상 (예: 두드러기)" className="form-input" />
          <button disabled={!na.allergen.trim() || busy === 'na'} className="btn-secondary disabled:opacity-40"
            onClick={() => run('na', () => api.post(`/ehr/residents/${elderlyId}/allergies`, na)
              .then(() => setNa({ allergen: '', severity: 'mild', reaction: '' })))}>
            추가
          </button>
        </div>

        <div className="grid sm:grid-cols-3 gap-4 pt-4 border-t border-slate-100">
          <Field label="식사 형태">
            <select value={form.texture_level ?? ''} onChange={set('texture_level')} className="form-input">
              <option value="">선택</option>
              {TEXTURE.map((t, i) => <option key={t} value={i}>{t}</option>)}
            </select>
          </Field>
          <Field label="점도증진제">
            <select value={form.thickener || ''} onChange={set('thickener')} className="form-input">
              {THICKENER.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          <Field label="치료식">
            <input value={form.therapeutic_diet || ''} onChange={set('therapeutic_diet')}
              placeholder="당뇨식, 저염식" className="form-input" />
          </Field>
        </div>
      </Card>

      {d.profile?.updated_at && (
        <p className="text-xs text-muted text-right">
          마지막 수정 {fmtDate(d.profile.updated_at)}{d.profile.updated_by ? ` · ${d.profile.updated_by}` : ''}
        </p>
      )}
    </div>
  )
}

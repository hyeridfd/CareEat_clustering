import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout, { Empty } from '../../components/care/CareLayout'
import { SortTh, TypeBadge, errMsg, fmtDate, sortRows, useSortState } from '../../components/care/CareUI'
import { startSurvey } from '../../lib/surveySession'

const STEPS = [
  { key: 'basic', label: '건강 프로파일', hint: '질환·기능·구강·인지' },
  { key: 'nutrition', label: '식사 섭취', hint: '5일 끼니별 기록' },
  { key: 'satisfaction', label: '만족·선호', hint: '급식 만족도와 음식 선호' },
]

function Dot({ done, partial }) {
  const c = done ? 'bg-emerald-500' : partial ? 'bg-amber-400' : 'bg-navy-100'
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${c}`} />
}

export default function RecordsPage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [msg, setMsg] = useState(null)
  const [q, setQ] = useState('')
  const [filter, setFilter] = useState('all')
  const [form, setForm] = useState({ open: false, name: '', elderly_id: '' })
  const [sort, toggleSort] = useSortState()

  // 열별 정렬 기준
  const SORT_VALUES = {
    name: (r) => r.display_name || r.elderly_id,
    basic: (r) => Number(!!r.surveys.basic),
    nutrition: (r) => r.surveys.nutrition_days || 0,
    satisfaction: (r) => Number(!!r.surveys.satisfaction),
    type: (r) => r.assessment?.type_code || null,
    assessed: (r) => r.assessment?.created_at || null,
  }

  const load = () => api.get('/care/overview').then((r) => setData(r.data)).catch((e) => setMsg({ kind: 'error', text: errMsg(e) }))
  useEffect(() => { load() }, [])

  const rows = useMemo(() => {
    if (!data) return []
    const list = data.residents
      .filter((r) => {
        const s = r.surveys
        const done = s.basic && s.nutrition_days >= 5 && s.satisfaction
        if (filter === 'done' && !done) return false
        if (filter === 'todo' && done) return false
        if (filter === 'none' && s.basic) return false
        if (q && !`${r.elderly_id} ${r.display_name}`.toLowerCase().includes(q.toLowerCase())) return false
        return true
      })
    const base = list.sort((a, b) => Number(b.surveys.basic) - Number(a.surveys.basic) || a.elderly_id.localeCompare(b.elderly_id))
    return sortRows(base, sort, SORT_VALUES)
  }, [data, filter, q, sort])

  const stats = useMemo(() => {
    const list = data?.residents || []
    const done = list.filter((r) => r.surveys.basic && r.surveys.nutrition_days >= 5 && r.surveys.satisfaction).length
    const started = list.filter((r) => r.surveys.basic).length
    return { total: list.length, done, started, none: list.length - started }
  }, [data])

  const openSurvey = async (r, e) => {
    e.stopPropagation()
    try {
      const { data } = await api.post(`/care/residents/${r.elderly_id}/survey-token`)
      startSurvey(data)
      navigate('/dashboard')
    } catch (err) {
      setMsg({ kind: 'error', text: errMsg(err) })
    }
  }

  const addResident = async (e) => {
    e.preventDefault()
    try {
      const { data: r } = await api.post('/care/residents', { name: form.name, elderly_id: form.elderly_id || undefined })
      setMsg({ kind: 'ok', text: `${form.name} 어르신을 등록했습니다 (ID: ${r.elderly_id}).` })
      setForm({ open: false, name: '', elderly_id: '' })
      load()
    } catch (err) {
      setMsg({ kind: 'error', text: errMsg(err) })
    }
  }

  return (
    <CareLayout
      title="기록"
      subtitle="어르신별 건강 프로파일과 식사 기록 현황이에요."
      actions={<button onClick={() => setForm({ ...form, open: !form.open })} className="btn-primary text-sm">어르신 등록</button>}
    >
      {msg && <p className={`mb-4 text-sm rounded-xl px-4 py-3 ${msg.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-navy-50 text-navy-800'}`}>{msg.text}</p>}

      {form.open && (
        <form onSubmit={addResident} className="surface p-5 mb-5 grid sm:grid-cols-4 gap-3 items-end">
          <div className="sm:col-span-2">
            <label className="form-label">성함 *</label>
            <input className="form-input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required placeholder="예: 김○순" />
          </div>
          <div>
            <label className="form-label">어르신 ID</label>
            <input className="form-input" value={form.elderly_id} onChange={(e) => setForm({ ...form, elderly_id: e.target.value })} placeholder="비우면 자동 생성" />
          </div>
          <button className="btn-primary">등록</button>
        </form>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[['전체 어르신', stats.total, 'all'], ['조사 완료', stats.done, 'done'], ['진행 중', stats.started - stats.done, 'todo'], ['조사 전', stats.none, 'none']].map(([label, v, key]) => (
          <button key={key} onClick={() => setFilter(filter === key ? 'all' : key)}
            className={`text-left rounded-2xl border p-4 bg-white transition ${filter === key ? 'border-navy-500 ring-2 ring-navy-100' : 'border-navy-100 hover:border-navy-200'}`}>
            <p className="text-xs font-medium text-muted">{label}</p>
            <p className="mt-1 text-2xl font-extrabold text-navy-900 tabular-nums">{v}<span className="ml-1 text-sm font-medium text-slate-400">명</span></p>
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="flex flex-wrap gap-3 text-xs text-muted">
          {STEPS.map((s) => <span key={s.key} className="inline-flex items-center gap-1.5"><Dot done /> {s.label} <span className="text-slate-400">· {s.hint}</span></span>)}
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="어르신 검색"
          className="ml-auto w-full sm:w-52 form-input py-2 rounded-full" />
      </div>

      {!data ? (
        <div className="surface p-12 text-center text-muted">불러오는 중…</div>
      ) : rows.length === 0 ? (
        <Empty title="해당하는 어르신이 없습니다" desc="어르신을 등록하거나 필터를 바꿔 보세요." />
      ) : (
        <div className="surface overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead>
              <tr className="text-left text-xs text-muted border-b border-navy-100">
                <SortTh label="어르신" sortKey="name" sort={sort} onSort={toggleSort} className="px-5 py-3" />
                <SortTh label="건강 프로파일" sortKey="basic" sort={sort} onSort={toggleSort} className="px-2 py-3" />
                <SortTh label="식사 섭취" sortKey="nutrition" sort={sort} onSort={toggleSort} className="px-2 py-3" />
                <SortTh label="만족·선호" sortKey="satisfaction" sort={sort} onSort={toggleSort} className="px-2 py-3" />
                <SortTh label="최근 진단" sortKey="type" sort={sort} onSort={toggleSort} className="px-2 py-3" />
                <SortTh label="평가일" sortKey="assessed" sort={sort} onSort={toggleSort} className="px-2 py-3" align="right" />
                <th className="px-5 py-3 text-right">조사 입력</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.elderly_id} onClick={() => navigate(`/care/residents/${r.elderly_id}`)}
                  className="border-b border-navy-50 last:border-0 hover:bg-navy-50/60 cursor-pointer">
                  <td className="px-5 py-3">
                    <p className="font-semibold text-navy-900">{r.display_name}</p>
                    {r.display_name !== r.elderly_id && <p className="text-xs text-slate-400">{r.elderly_id}</p>}
                  </td>
                  <td className="px-2 py-3"><Dot done={r.surveys.basic} /></td>
                  <td className="px-2 py-3">
                    <span className="inline-flex items-center gap-2">
                      <Dot done={r.surveys.nutrition_days >= 5} partial={r.surveys.nutrition_days > 0} />
                      <span className="text-xs text-muted">{r.surveys.nutrition_days}/5일</span>
                    </span>
                  </td>
                  <td className="px-2 py-3"><Dot done={r.surveys.satisfaction} /></td>
                  <td className="px-2 py-3">
                    {r.assessment
                      ? <span className="inline-flex items-center gap-2"><TypeBadge code={r.assessment.type_code} name={r.assessment.type_name} />
                          <Link to={`/care/residents/${r.elderly_id}/report`} onClick={(e) => e.stopPropagation()} className="text-[11px] font-semibold text-navy-600 hover:underline">리포트</Link>
                        </span>
                      : <span className="text-xs text-slate-400">미평가</span>}
                  </td>
                  <td className="px-2 py-3 text-right text-xs text-muted">{r.assessment ? fmtDate(r.assessment.created_at) : '-'}</td>
                  <td className="px-5 py-3 text-right">
                    <button onClick={(e) => openSurvey(r, e)} className="btn-secondary text-xs py-1.5 px-3">
                      {r.surveys.basic ? '조사 이어하기' : '조사 입력'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-4 text-xs text-muted">「조사 입력」을 누르면 그 어르신의 조사 화면으로 바로 들어갑니다. 건강 프로파일이 있어야 진단(유형 분류)이 가능합니다.</p>
    </CareLayout>
  )
}

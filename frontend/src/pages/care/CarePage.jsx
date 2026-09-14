import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { Card, LEVELS, LevelPill, ScoreBar, SOLUTION_STATUS, TRANSITION, TypeBadge, errMsg, fmtDate } from '../../components/care/CareUI'

const LEVEL_KEYS = ['high', 'medium', 'low', 'unassessed']

function SurveyDots({ s }) {
  const dot = (ok, label) => (
    <span title={label} className={`inline-block w-2 h-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-gray-200'}`} />
  )
  return (
    <span className="inline-flex items-center gap-1" title="기초 · 영양(5일) · 만족도">
      {dot(s.basic, '기초')}
      {dot(s.nutrition_days >= 5, `영양 ${s.nutrition_days}/5일`)}
      {dot(s.satisfaction, '만족도')}
    </span>
  )
}

export default function CarePage() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [force, setForce] = useState(false)
  const [notice, setNotice] = useState(null)
  const [level, setLevel] = useState('all')
  const [type, setType] = useState('all')
  const [q, setQ] = useState('')

  const load = () => {
    setLoading(true)
    api.get('/care/overview').then((r) => setData(r.data))
      .catch((e) => setNotice({ kind: 'error', text: errMsg(e) }))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const runAssess = async () => {
    setRunning(true); setNotice(null)
    try {
      const { data: r } = await api.post('/care/assess', { force }, { timeout: 120000 })
      const changes = r.type_changes.length ? ` · 유형 변화 ${r.type_changes.length}명` : ''
      setNotice({ kind: 'ok', text: `평가 완료: ${r.assessed.length}명 평가, ${r.skipped.length}명은 설문 변경이 없어 생략${changes} (모델 ${r.model_version})` })
      load()
    } catch (e) {
      setNotice({ kind: 'error', text: errMsg(e) })
    } finally {
      setRunning(false)
    }
  }

  const rows = useMemo(() => {
    if (!data) return []
    return data.residents.filter((r) => {
      const lv = r.assessment?.priority_level || 'unassessed'
      if (level !== 'all' && lv !== level) return false
      if (type !== 'all' && r.assessment?.type_code !== type) return false
      if (q && !`${r.elderly_id} ${r.display_name}`.toLowerCase().includes(q.toLowerCase())) return false
      return true
    })
  }, [data, level, type, q])

  const types = data?.model?.types || []

  return (
    <CareLayout
      title="진단"
      subtitle="설문 데이터로 어르신 유형과 돌봄 우선순위를 계산합니다."
      actions={
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-xs text-muted">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} /> 전체 재평가(설문 변경 없어도 다시 계산)
          </label>
          <button onClick={runAssess} disabled={running} className="btn-primary text-sm">
            {running ? '평가 중…' : '유형·우선순위 평가 실행'}
          </button>
        </div>
      }
    >
      <div className="space-y-5">
        {/* 등급별 현황 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {LEVEL_KEYS.map((k) => {
            const active = level === k
            const label = k === 'unassessed' ? '미평가' : LEVELS[k].label
            return (
              <button key={k} onClick={() => setLevel(active ? 'all' : k)}
                className={`text-left rounded-2xl border p-4 transition ${active ? 'border-blue-500 ring-2 ring-blue-100 bg-white' : 'border-gray-200 bg-white hover:border-gray-300'}`}>
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${k === 'unassessed' ? 'bg-gray-300' : LEVELS[k].bar}`} />
                  <span className="text-xs font-medium text-gray-500">{label}</span>
                </div>
                <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">{data?.counts?.[k] ?? '–'}<span className="text-sm font-medium text-gray-400 ml-1">명</span></p>
              </button>
            )
          })}
        </div>

        {/* 안내 · 알림 */}
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="text-sm text-slate-600 max-w-2xl leading-6">
              설문이 바뀐 어르신만 다시 평가하며, 이전 평가와 비교해 변화(체중·섭취·유형)를 반영합니다.
              결과는 담당자가 확인한 뒤 솔루션으로 이어집니다.
            </div>
          </div>
          {notice && (
            <p className={`mt-4 text-sm rounded-xl px-4 py-3 ${notice.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-navy-50 text-navy-800'}`}>{notice.text}</p>
          )}
          {data?.model?.error && <p className="mt-4 text-sm rounded-xl px-4 py-3 bg-amber-50 text-amber-800">유형 모델 없음: {data.model.error}</p>}
        </Card>

        {/* 필터 */}
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => setType('all')} className={`px-3 py-1.5 rounded-full text-xs font-medium ${type === 'all' ? 'bg-gray-900 text-white' : 'bg-white border border-gray-200 text-gray-600'}`}>전체 유형</button>
          {types.map((t) => (
            <button key={t.code} onClick={() => setType(type === t.code ? 'all' : t.code)}
              className={`rounded-full ${type === t.code ? 'ring-2 ring-offset-1 ring-blue-400' : ''}`}>
              <TypeBadge code={t.code} name={t.name} />
            </button>
          ))}
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="어르신 검색"
            className="ml-auto w-full sm:w-48 border border-gray-200 rounded-full px-4 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-300" />
        </div>

        {/* 목록 */}
        <div className="bg-white rounded-2xl border border-gray-200 shadow-sm overflow-x-auto">
          <table className="w-full text-sm min-w-[860px]">
            <thead>
              <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                <th className="px-4 py-3 w-10">#</th>
                <th className="px-2 py-3">어르신</th>
                <th className="px-2 py-3">유형</th>
                <th className="px-2 py-3 w-44">돌봄 우선순위</th>
                <th className="px-2 py-3">주요 요인</th>
                <th className="px-2 py-3">조사</th>
                <th className="px-2 py-3">솔루션</th>
                <th className="px-4 py-3 text-right">평가일</th>
              </tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={8} className="px-4 py-10 text-center text-gray-400">불러오는 중…</td></tr>}
              {!loading && rows.length === 0 && <tr><td colSpan={8} className="px-4 py-10 text-center text-gray-400">해당하는 어르신이 없습니다.</td></tr>}
              {!loading && rows.map((r, i) => {
                const a = r.assessment
                const tr = a?.transition?.kind && TRANSITION[a.transition.kind]
                return (
                  <tr key={r.elderly_id} onClick={() => navigate(`/care/residents/${r.elderly_id}`)}
                    className="border-b border-gray-50 hover:bg-blue-50/40 cursor-pointer">
                    <td className="px-4 py-3 text-gray-400 tabular-nums">{i + 1}</td>
                    <td className="px-2 py-3">
                      <div className="font-semibold text-gray-900">{r.display_name}</div>
                      {r.display_name !== r.elderly_id && <div className="text-xs text-gray-400">{r.elderly_id}</div>}
                    </td>
                    <td className="px-2 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <TypeBadge code={a?.type_code} name={a?.type_name} />
                        <div className="flex gap-1">
                          {tr && <span className={`text-[11px] rounded px-1.5 py-0.5 ${tr.cls}`}>{tr.label}</span>}
                          {a?.is_borderline && <span className="text-[11px] rounded px-1.5 py-0.5 bg-violet-50 text-violet-700">경계</span>}
                        </div>
                      </div>
                    </td>
                    <td className="px-2 py-3">
                      {a ? (<div className="space-y-1"><ScoreBar score={a.priority_score} level={a.priority_level} /><LevelPill level={a.priority_level} /></div>) : <span className="text-xs text-gray-400">–</span>}
                    </td>
                    <td className="px-2 py-3">
                      <div className="flex flex-wrap gap-1 max-w-xs">
                        {(r.top_factors || []).map((f) => <span key={f} className="text-[11px] bg-gray-100 text-gray-700 rounded px-1.5 py-0.5">{f}</span>)}
                      </div>
                    </td>
                    <td className="px-2 py-3"><SurveyDots s={r.surveys} /></td>
                    <td className="px-2 py-3">
                      {r.solution ? <span className={`text-[11px] rounded-full px-2 py-0.5 ${SOLUTION_STATUS[r.solution.status]?.cls}`}>{SOLUTION_STATUS[r.solution.status]?.label}</span> : <span className="text-xs text-gray-400">없음</span>}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-500">{fmtDate(a?.created_at)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">우선순위 점수는 유형 위험도, 현재 상태(영양·섭취·삼킴 등), 직전 평가 대비 변화를 더한 값입니다. 최종 판단은 담당자가 합니다.</p>
      </div>
    </CareLayout>
  )
}

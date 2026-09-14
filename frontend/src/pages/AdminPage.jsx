import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../lib/api'
import useAuthStore from '../lib/authStore'
import StaffAdmin from '../components/care/StaffAdmin'
import FacilityApplications from '../components/care/FacilityApplications'

const TABS = ['가입 신청', '요양원', '조사원', '어르신', '설문 진행 현황', '담당자 계정']

function StatCard({ label, value, total, color = 'blue' }) {
  const pct = total ? Math.round((value / total) * 100) : 0
  const colors = { blue: 'text-blue-600', green: 'text-green-600', yellow: 'text-yellow-600', purple: 'text-purple-600' }
  return (
    <div className="card py-4 text-center">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-bold ${colors[color]}`}>{value}</p>
      {total && <p className="text-xs text-gray-400 mt-1">{pct}%</p>}
    </div>
  )
}

function DataTable({ data, emptyMsg = '데이터가 없습니다.' }) {
  if (!data || data.length === 0) return <p className="text-sm text-gray-400 py-4">{emptyMsg}</p>
  const keys = Object.keys(data[0]).filter(k => !['created_at','updated_at','last_updated'].includes(k))
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50">
            {keys.map(k => <th key={k} className="text-left px-3 py-2 text-xs text-gray-500 font-medium">{k}</th>)}
          </tr>
        </thead>
        <tbody>
          {data.map((row, i) => (
            <tr key={i} className="border-t border-gray-100 hover:bg-gray-50">
              {keys.map(k => (
                <td key={k} className="px-3 py-2 text-gray-700">
                  {typeof row[k] === 'boolean'
                    ? (row[k] ? '✅' : '❌')
                    : String(row[k] ?? '-')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminPage() {
  const navigate = useNavigate()
  const { logout } = useAuthStore()
  const [tab, setTab] = useState(0)
  const [nursingHomes, setNursingHomes] = useState([])
  const [surveyors, setSurveyors] = useState([])
  const [elderly, setElderly] = useState([])
  const [progress, setProgress] = useState({ rows: [], stats: {} })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      api.get('/admin/nursing-homes'),
      api.get('/admin/surveyors'),
      api.get('/admin/elderly'),
      api.get('/admin/progress'),
    ]).then(([nh, sv, el, pr]) => {
      setNursingHomes(nh.data)
      setSurveyors(sv.data)
      setElderly(el.data)
      setProgress(pr.data)
    }).finally(() => setLoading(false))
  }, [])

  const { stats } = progress

  return (
    <div className="min-h-screen bg-navy-50/40">
      <header className="bg-white shadow-sm px-4 py-3 flex items-center justify-between">
        <h1 className="text-lg font-extrabold tracking-tight text-navy-900">Care-Eat 운영 관리자</h1>
        <button onClick={() => { logout(); navigate('/login') }} className="text-sm text-gray-500 hover:text-red-600">로그아웃</button>
      </header>

      <div className="max-w-5xl mx-auto p-4 space-y-4">
        {/* 통계 카드 */}
        {!loading && stats.total > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            <StatCard label="전체 응답자" value={stats.total} color="blue" />
            <StatCard label="기초 완료" value={stats.basic_completed} total={stats.total} color="green" />
            <StatCard label="영양 완료" value={stats.nutrition_completed} total={stats.total} color="yellow" />
            <StatCard label="만족도 완료" value={stats.satisfaction_completed} total={stats.total} color="purple" />
            <StatCard label="전체 완료" value={stats.all_completed} total={stats.total} color="green" />
          </div>
        )}

        {/* 탭 */}
        <div className="card">
          <div className="flex gap-2 mb-4 flex-wrap">
            {TABS.map((t, i) => (
              <button
                key={t}
                onClick={() => setTab(i)}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
                  tab === i ? 'bg-navy-900 text-white' : 'bg-white border border-navy-100 text-navy-700 hover:border-navy-300'
                }`}
              >{t}</button>
            ))}
          </div>

          {loading ? (
            <p className="text-sm text-gray-400 py-4">불러오는 중...</p>
          ) : (
            <>
              {tab === 0 && <FacilityApplications />}
              {tab === 1 && <DataTable data={nursingHomes} emptyMsg="등록된 요양원이 없습니다." />}
              {tab === 2 && <DataTable data={surveyors} emptyMsg="등록된 조사원이 없습니다." />}
              {tab === 3 && <DataTable data={elderly} emptyMsg="등록된 어르신이 없습니다." />}
              {tab === 4 && <DataTable data={progress.rows} emptyMsg="설문 진행 현황이 없습니다." />}
              {tab === 5 && <StaffAdmin nursingHomes={nursingHomes} />}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

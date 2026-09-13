import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import useAuthStore from '../../lib/authStore'

export default function StaffLoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [staffId, setStaffId] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setLoading(true); setError('')
    try {
      const { data } = await api.post('/auth/staff-login', { staff_id: staffId.trim(), password })
      setAuth(data.token, {
        role: 'staff', staff_id: data.staff_id, staff_name: data.staff_name,
        nursing_home_id: data.nursing_home_id, nursing_home_name: data.nursing_home_name,
      })
      navigate('/care')
    } catch (err) {
      setError(err.response?.data?.detail || '로그인에 실패했습니다.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-5"
      style={{ background: 'linear-gradient(160deg, #0a2e6e 0%, #1151b8 45%, #2979d4 100%)' }}>
      <div className="w-full max-w-sm">
        <div className="text-center mb-6">
          <p className="text-blue-200 text-xs font-semibold tracking-widest mb-2">CARE MANAGEMENT</p>
          <h1 className="text-2xl font-bold text-white">요양원 돌봄 관리</h1>
          <p className="text-blue-100 text-sm mt-2">유형 · 돌봄 우선순위 · 보호자 알림</p>
        </div>
        <form onSubmit={submit} className="rounded-3xl bg-white p-6 shadow-2xl space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-500 mb-1.5 block">담당자 ID</label>
            <input className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              value={staffId} onChange={(e) => setStaffId(e.target.value)} autoComplete="username" required />
          </div>
          <div>
            <label className="text-xs font-semibold text-gray-500 mb-1.5 block">비밀번호</label>
            <input type="password" className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
          </div>
          {error && <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-xl px-4 py-3">{error}</p>}
          <button disabled={loading} className="w-full py-3.5 rounded-xl text-white font-bold text-sm disabled:opacity-60"
            style={{ background: 'linear-gradient(135deg, #1151b8 0%, #2979d4 100%)' }}>
            {loading ? '로그인 중...' : '로그인'}
          </button>
          <p className="text-xs text-gray-400 text-center">계정은 관리자에게 발급받으세요.</p>
        </form>
        <div className="text-center mt-4">
          <Link to="/login" className="text-sm text-blue-100 hover:text-white">← 설문 조사 로그인으로</Link>
        </div>
      </div>
    </div>
  )
}

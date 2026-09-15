import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import useAuthStore from '../../lib/authStore'
import { endSurvey } from '../../lib/surveySession'
import { Lab, LogoMark } from '../../components/brand/Brand'
import heroCare from '../../assets/hero-care.jpg'

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
    endSurvey()
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
    <div className="min-h-screen lg:grid lg:grid-cols-2">
      {/* 좌: 브랜드 */}
      <div className="relative hidden lg:flex flex-col justify-between bg-navy-grad text-white p-12 overflow-hidden">
        {/* 배경 사진 — 어르신이 오른쪽에 오도록 잡고, 왼쪽 글자 자리는 네이비로 덮는다 */}
        <img
          src={heroCare}
          alt=""
          aria-hidden
          className="absolute inset-0 h-full w-full object-cover opacity-[0.55]"
          style={{ objectPosition: '60% 50%' }}
        />
        <div aria-hidden className="absolute inset-0" style={{
          background:
            'linear-gradient(95deg, rgba(7,32,77,0.97) 0%, rgba(7,32,77,0.90) 30%, rgba(7,32,77,0.58) 60%, rgba(10,46,110,0.28) 100%),' +
            'linear-gradient(to top, rgba(7,32,77,0.88) 0%, rgba(7,32,77,0) 34%)',
        }} />
        <div aria-hidden className="absolute inset-0 opacity-[0.13]"
          style={{ backgroundImage: 'radial-gradient(circle at 30% 20%, #fff 1px, transparent 1px)', backgroundSize: '26px 26px' }} />
        <Link to="/" className="relative flex items-center gap-3">
          <LogoMark className="w-10 h-10" tone="white" />
          <span className="text-xl font-extrabold tracking-tight">Care<span className="text-sky-300">-</span>Eat</span>
        </Link>
        <div className="relative max-w-md">
          <h2 className="text-3xl font-extrabold leading-snug">
            오늘 누구를<br />먼저 챙겨야 할까요?
          </h2>
          <p className="mt-5 text-navy-100/80 leading-7">
            어르신의 건강·식사 기록을 유형으로 진단하고, 돌봄 계획과 보호자 안내까지 한 화면에서 이어 갑니다.
          </p>
        </div>
        <Lab tone="white" logo className="relative" />
      </div>

      {/* 우: 로그인 */}
      <div className="flex items-center justify-center px-5 py-16 bg-white">
        <div className="w-full max-w-sm">
          <div className="lg:hidden mb-8 flex justify-center">
            <Link to="/" className="flex items-center gap-2.5">
              <LogoMark className="w-10 h-10" />
              <span className="text-xl font-extrabold tracking-tight text-navy-900">Care<span className="text-navy-500">-</span>Eat</span>
            </Link>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-navy-900">요양시설 담당자 로그인</h1>
          <p className="mt-2 text-sm text-muted">돌봄 관리 화면으로 들어갑니다.</p>

          <form onSubmit={submit} className="mt-8 space-y-4">
            <div>
              <label className="form-label">담당자 ID</label>
              <input className="form-input" value={staffId} onChange={(e) => setStaffId(e.target.value)} autoComplete="username" required />
            </div>
            <div>
              <label className="form-label">비밀번호</label>
              <input type="password" className="form-input" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
            </div>
            {error && <p className="text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{error}</p>}
            <button disabled={loading} className="btn-primary w-full py-3 rounded-xl">{loading ? '로그인 중…' : '로그인'}</button>
          </form>

          <div className="mt-8 rounded-2xl bg-navy-50/70 px-5 py-4 text-sm">
            <p className="font-semibold text-navy-900">계정이 없으신가요?</p>
            <p className="mt-1 text-muted leading-6">시설 가입을 신청하시면 확인 후 계정을 보내 드립니다.</p>
            <Link to="/signup" className="mt-3 inline-flex btn-secondary text-sm">시설 가입 신청</Link>
          </div>

          <div className="mt-6 flex justify-between text-xs text-muted">
            <Link to="/" className="hover:text-navy-700">← 서비스 소개</Link>
            <Link to="/login" className="hover:text-navy-700">조사원 설문 로그인</Link>
          </div>
        </div>
      </div>
    </div>
  )
}

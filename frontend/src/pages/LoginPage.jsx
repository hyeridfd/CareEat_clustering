import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api from '../lib/api'
import useAuthStore from '../lib/authStore'

const NURSING_HOMES = [
  { id: 'NH001', name: '헤리티지 실버케어 분당', prefix: 'HS', surveyors: ['SRV01','SRV02','SRV03'] },
  { id: 'NH002', name: '마리아의 집',            prefix: 'MH', surveyors: ['SRV01_NH002','SRV02_NH002','SRV03_NH002'] },
  { id: 'NH003', name: '과천시립요양원',          prefix: 'GS', surveyors: ['SRV01_NH003','SRV02_NH003','SRV03_NH003'] },
]

export default function LoginPage() {
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)

  const [selectedNH, setSelectedNH] = useState(NURSING_HOMES[0])
  const [surveyorId, setSurveyorId] = useState(NURSING_HOMES[0].surveyors[0])
  const [elNum, setElNum] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const [adminOpen, setAdminOpen] = useState(false)
  const [adminPw, setAdminPw] = useState('')
  const [adminError, setAdminError] = useState('')

  const handleNHChange = (e) => {
    const nh = NURSING_HOMES.find(n => n.id === e.target.value)
    setSelectedNH(nh)
    setSurveyorId(nh.surveyors[0])
    setElNum('')
    setError('')
  }

  const handleLogin = async (e) => {
    e.preventDefault()
    if (!elNum) { setError('어르신 번호를 입력해주세요.'); return }
    setLoading(true); setError('')
    try {
      const res = await api.post('/auth/login', {
        nursing_home_id: selectedNH.id,
        surveyor_id: surveyorId,
        elderly_id: `${selectedNH.prefix}${elNum}`,
      })
      setAuth(res.data.token, {
        nursing_home_id: res.data.nursing_home_id,
        surveyor_id: res.data.surveyor_id,
        elderly_id: res.data.elderly_id,
        nursing_home_name: res.data.nursing_home_name,
      })
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || '로그인 실패')
    } finally {
      setLoading(false)
    }
  }

  const handleAdminLogin = async (e) => {
    e.preventDefault()
    setAdminError('')
    try {
      const res = await api.post('/auth/admin-login', { password: adminPw })
      setAuth(res.data.token, null, true)
      navigate('/admin')
    } catch (err) {
      setAdminError(err.response?.data?.detail || '비밀번호가 올바르지 않습니다.')
    }
  }

  // 드롭다운 표시용 조사원 ID (NH002/NH003 suffix 숨김)
  const displaySurveyor = (id) => id.replace(`_${selectedNH.id}`, '')

  return (
    <div className="min-h-screen flex flex-col relative" style={{
      backgroundImage: 'url(https://fmrxrvqccphjrsxpkwof.supabase.co/storage/v1/object/public/assets/login.png)',
      backgroundSize: 'cover',
      backgroundPosition: 'center 30%',
    }}>
      <div className="absolute inset-0" style={{
        background: 'linear-gradient(160deg, rgba(10,46,110,0.88) 0%, rgba(17,81,184,0.82) 40%, rgba(41,121,212,0.78) 70%, rgba(79,172,254,0.72) 100%)'
      }} />
      <div className="relative z-10 flex flex-col min-h-screen">

        <div className="flex-1 flex flex-col items-center justify-center px-5 pt-12 pb-6">
          <div className="text-center mb-6">
            <Link to="/" className="inline-flex items-center gap-2 mb-4 text-sky-200 hover:text-white text-sm font-bold tracking-tight">
              Care<span className="text-white/60">-</span>Eat
            </Link>
            <h1 className="text-2xl font-bold text-white tracking-tight leading-snug mb-3">
              요양원 입소 고령자 대상<br />건강 프로파일 분석 및 선호도 조사
            </h1>
            <div className="w-12 h-0.5 mx-auto rounded-full" style={{ background: 'rgba(255,255,255,0.4)' }}></div>
          </div>

          <div className="w-full max-w-sm">
            <div className="rounded-3xl p-6 shadow-2xl"
              style={{ background: 'rgba(255,255,255,0.97)', backdropFilter: 'blur(20px)' }}>

              <h2 className="text-base font-bold text-gray-800 mb-5 flex items-center gap-2">
                <span className="w-1 h-5 rounded-full bg-blue-600 inline-block"></span>
                설문 조사 로그인
              </h2>

              <form onSubmit={handleLogin} className="space-y-4">

                {/* 요양원 선택 */}
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">요양원</label>
                  <select
                    className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm bg-white text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                    value={selectedNH.id}
                    onChange={handleNHChange}>
                    {NURSING_HOMES.map(nh => (
                      <option key={nh.id} value={nh.id}>{nh.name}</option>
                    ))}
                  </select>
                </div>

                {/* 요양원 ID (자동) */}
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">요양원 ID</label>
                  <input
                    className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm bg-gray-50 text-gray-400 font-medium"
                    value={selectedNH.id} disabled />
                </div>

                {/* 조사원 ID */}
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">조사원 ID</label>
                  <select
                    className="w-full border border-gray-200 rounded-xl px-4 py-3 text-sm bg-white text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                    value={surveyorId}
                    onChange={e => setSurveyorId(e.target.value)}>
                    {selectedNH.surveyors.map(v => (
                      <option key={v} value={v}>{displaySurveyor(v)}</option>
                    ))}
                  </select>
                </div>

                {/* 어르신 ID */}
                <div>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5 block">어르신 ID</label>
                  <div className="flex gap-2">
                    <div className="flex items-center justify-center px-3 border border-gray-200 rounded-xl bg-gray-50 text-gray-500 text-sm font-bold shrink-0">
                      {selectedNH.prefix}
                    </div>
                    <input
                      className="flex-1 border border-gray-200 rounded-xl px-4 py-3 text-sm bg-white text-gray-800 font-medium focus:outline-none focus:ring-2 focus:ring-blue-400"
                      placeholder="01"
                      value={elNum}
                      onChange={e => setElNum(e.target.value.replace(/\D/g, ''))}
                      maxLength={4}
                      inputMode="numeric"
                    />
                  </div>
                  <p className="text-xs text-gray-400 mt-1 pl-1">
                    예: {selectedNH.prefix}01, {selectedNH.prefix}02 ...
                  </p>
                </div>

                {error && (
                  <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
                    <span className="text-red-500 text-sm">⚠️</span>
                    <p className="text-sm text-red-600">{error}</p>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-3.5 rounded-xl text-white font-bold text-sm tracking-wide shadow-lg transition-all disabled:opacity-60"
                  style={{ background: loading ? '#93c5fd' : 'linear-gradient(135deg, #1151b8 0%, #2979d4 100%)' }}>
                  {loading ? '로그인 중...' : '로그인 →'}
                </button>
              </form>
            </div>

            {/* 요양원 담당자 (돌봄 관리) */}
            <Link to="/staff-login"
              className="mt-3 w-full px-5 py-3.5 rounded-2xl text-sm text-blue-100 font-medium flex justify-between items-center"
              style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.2)' }}>
              <span className="flex items-center gap-2"><span className="text-base">🏥</span> 요양시설 담당자 로그인 (Care-Eat 돌봄 관리)</span>
              <span className="text-blue-200 text-xs">→</span>
            </Link>

            {/* 관리자 로그인 */}
            <div className="mt-3 rounded-2xl overflow-hidden"
              style={{ background: 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.2)' }}>
              <button
                className="w-full px-5 py-3.5 text-left text-sm text-blue-100 font-medium flex justify-between items-center"
                onClick={() => setAdminOpen(!adminOpen)}>
                <span className="flex items-center gap-2">
                  <span className="text-base">🔐</span> 관리자 로그인
                </span>
                <span className="text-blue-200 text-xs">{adminOpen ? '▲' : '▼'}</span>
              </button>

              {adminOpen && (
                <form onSubmit={handleAdminLogin} className="px-5 pb-4 space-y-3">
                  <input
                    type="password"
                    className="w-full border border-white/20 rounded-xl px-4 py-3 text-sm bg-white/10 text-white placeholder-blue-200 focus:outline-none focus:ring-2 focus:ring-white/40"
                    value={adminPw}
                    onChange={e => setAdminPw(e.target.value)}
                    placeholder="비밀번호 입력"
                  />
                  {adminError && <p className="text-xs text-red-300">{adminError}</p>}
                  <button type="submit"
                    className="w-full py-3 rounded-xl text-sm font-semibold text-blue-900 transition-all"
                    style={{ background: 'rgba(255,255,255,0.9)' }}>
                    관리자로 로그인
                  </button>
                </form>
              )}
            </div>
          </div>
        </div>

        <div className="text-center pb-8 px-4">
          <p className="text-xs text-blue-200 leading-relaxed">
            서울대학교 농생공학부 정밀식의약솔루션 연구실<br />
            글로벌 블루푸드 미래리더 양성 프로젝트
          </p>
        </div>
      </div>
    </div>
  )
}

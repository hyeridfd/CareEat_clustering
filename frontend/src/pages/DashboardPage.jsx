import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../lib/api'
import useAuthStore from '../lib/authStore'

const SURVEYS = [
  { key: 'basic', label: '기초 조사표', icon: '📝', path: '/survey/basic', field: 'basic_survey_completed' },
  { key: 'nutrition', label: '영양 조사표', icon: '🥗', path: '/survey/nutrition', field: 'nutrition_survey_completed' },
  { key: 'satisfaction', label: '만족도 및 선호도 조사표', icon: '😊', path: '/survey/satisfaction', field: 'satisfaction_survey_completed' },
  // { key: 'bluefood', label: '블루푸드 선호도 조사', icon: '🐟', path: '/survey/bluefood', field: 'bluefood_survey_completed' },
]

export default function DashboardPage() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const [progress, setProgress] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get('/surveys/progress')
      .then(r => setProgress(r.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const completedCount = progress ? SURVEYS.filter(s => progress[s.field]).length : 0
  const allDone = completedCount === SURVEYS.length

  return (
    <div className="min-h-screen flex flex-col relative" style={{
      backgroundImage: 'url(https://fmrxrvqccphjrsxpkwof.supabase.co/storage/v1/object/public/assets/login.png)',
      backgroundSize: 'cover',
      backgroundPosition: 'center 30%',
    }}>
      {/* 그라데이션 오버레이 */}
      <div className="absolute inset-0" style={{
        background: 'linear-gradient(160deg, rgba(10,46,110,0.92) 0%, rgba(17,81,184,0.87) 40%, rgba(41,121,212,0.83) 70%, rgba(79,172,254,0.80) 100%)'
      }} />

      <div className="relative z-10 flex flex-col min-h-screen">
        {/* 상단 헤더 */}
        <header className="px-5 pt-12 pb-4">
          {/* 사용자 정보 */}
          <div className="flex items-start justify-between mb-5">
            <div>
              <p className="text-blue-200 text-xs font-medium mb-1">설문 조사</p>
              <h1 className="text-white text-xl font-bold leading-tight">
                {user?.nursing_home_name || user?.nursing_home_id}
              </h1>
              <p className="text-blue-200 text-sm mt-0.5">
                조사원 {user?.surveyor_id} · 어르신 {user?.elderly_id}
              </p>
            </div>
            <button
              onClick={() => { logout(); navigate('/login') }}
              className="text-xs text-blue-200 border border-blue-300/40 px-3 py-1.5 rounded-full hover:bg-white/10 transition-colors mt-1">
              로그아웃
            </button>
          </div>

          {/* 진행률 바 */}
          <div className="rounded-2xl p-4" style={{ background: 'rgba(255,255,255,0.12)', backdropFilter: 'blur(10px)', border: '1px solid rgba(255,255,255,0.2)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-white text-sm font-semibold">전체 진행 현황</span>
              {allDone
                ? <span className="text-xs bg-green-400 text-white px-2 py-0.5 rounded-full font-medium">🎉 완료!</span>
                : <span className="text-blue-200 text-xs">{completedCount} / {SURVEYS.length} 완료</span>
              }
            </div>
            {/* 프로그레스 바 */}
            <div className="w-full rounded-full h-2 mb-1" style={{ background: 'rgba(255,255,255,0.2)' }}>
              <div className="h-2 rounded-full transition-all duration-500"
                style={{
                  width: `${(completedCount / SURVEYS.length) * 100}%`,
                  background: allDone ? '#4ade80' : 'linear-gradient(90deg, #60a5fa, #a5f3fc)'
                }} />
            </div>
          </div>
        </header>

        {/* 설문 목록 */}
        <div className="flex-1 px-5 pb-8">
          <p className="text-blue-100 text-xs font-semibold uppercase tracking-wide mb-3">설문 선택</p>

          {loading ? (
            <div className="text-center py-8 text-blue-200 text-sm">불러오는 중...</div>
          ) : (
            <div className="space-y-3">
              {SURVEYS.map((s, i) => {
                const nutritionDays = progress?.nutrition_completed_days || 0
                const done = s.key === 'nutrition'
                  ? nutritionDays >= 5
                  : progress?.[s.field]
                const partial = s.key === 'nutrition' && nutritionDays > 0 && nutritionDays < 5
                return (
                  <button
                    key={s.key}
                    onClick={() => navigate(s.path)}
                    className="w-full flex items-center justify-between p-4 rounded-2xl transition-all active:scale-98"
                    style={{
                      background: done ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.95)',
                      backdropFilter: 'blur(10px)',
                      border: done ? '1px solid rgba(74,222,128,0.4)' : '1px solid rgba(255,255,255,0.3)',
                      boxShadow: '0 4px 15px rgba(0,0,0,0.1)',
                    }}>
                    <div className="flex items-center gap-3">
                      {/* 번호 뱃지 */}
                      <div className="w-9 h-9 rounded-xl flex items-center justify-center text-sm font-bold shrink-0"
                        style={{
                          background: done ? 'rgba(74,222,128,0.3)' : 'linear-gradient(135deg, #1151b8, #2979d4)',
                          color: done ? '#4ade80' : 'white'
                        }}>
                        {done ? '✓' : i + 1}
                      </div>
                      <div className="text-left">
                        <p className={`font-semibold text-sm ${done ? 'text-white' : 'text-gray-800'}`}>
                          {s.label}
                        </p>
                        <p className={`text-xs mt-0.5 ${done ? 'text-green-300' : partial ? 'text-orange-300' : 'text-gray-400'}`}>
                          {s.key === 'nutrition'
                            ? nutritionDays >= 5
                              ? '완료됨 (5/5일) · 수정 가능'
                              : nutritionDays > 0
                              ? `${nutritionDays}/5일 완료 · 수정 가능`
                              : '미완료'
                            : done ? '완료됨 · 수정 가능' : '미완료'
                          }
                        </p>
                      </div>
                    </div>
                    <div className={`text-lg ${done ? 'text-green-300' : 'text-blue-500'}`}>→</div>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* 하단 */}
        <div className="text-center pb-6">
          <p className="text-xs text-blue-200/70">서울대학교 농생명공학부 · 글로벌 블루푸드 미래리더 양성 프로젝트</p>
        </div>
      </div>
    </div>
  )
}
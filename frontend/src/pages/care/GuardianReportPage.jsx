import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'

// 보호자용 공개 리포트 (로그인 불필요 · 토큰 링크)
const base = import.meta.env.VITE_API_URL || '/api'

export default function GuardianReportPage() {
  const { token } = useParams()
  const [r, setR] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    axios.get(`${base}/public/report/${token}`)
      .then((res) => setR(res.data))
      .catch((e) => setErr(e.response?.data?.detail || '리포트를 불러올 수 없습니다.'))
  }, [token])

  return (
    <div className="min-h-screen bg-[#f6f7f9]">
      <div className="max-w-md mx-auto px-5 py-8">
        {err && <div className="rounded-2xl bg-white p-6 text-center text-gray-600 shadow-sm">{err}</div>}
        {!err && !r && <div className="text-center text-gray-400 py-20">불러오는 중…</div>}
        {r && (
          <>
            <p className="text-xs font-semibold text-blue-600">{r.facility}</p>
            <h1 className="mt-1 text-2xl font-bold text-gray-900 leading-snug">{r.resident} 어르신<br />건강·식사 돌봄 안내</h1>
            <p className="mt-2 text-sm text-gray-500">{r.guardian}님께 · 평가일 {r.assessed_on}</p>

            <section className="mt-6 rounded-2xl bg-white p-5 shadow-sm">
              <p className="text-xs text-gray-500">관리 구분</p>
              <p className="mt-1 text-lg font-bold text-gray-900">{r.care_group}</p>
              {r.focus?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {r.focus.map((x) => <span key={x} className="rounded-full bg-blue-50 text-blue-700 text-xs px-2.5 py-1">{x}</span>)}
                </div>
              )}
            </section>

            <section className="mt-4 rounded-2xl bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-gray-800 mb-2">시설에서 드리는 말씀</h2>
              <p className="text-[15px] leading-7 text-gray-700 whitespace-pre-line">{r.message}</p>
            </section>

            {r.meal_guidance?.length > 0 && (
              <section className="mt-4 rounded-2xl bg-white p-5 shadow-sm">
                <h2 className="text-sm font-bold text-gray-800 mb-2">식사는 이렇게 챙기고 있어요</h2>
                <ul className="space-y-2">
                  {r.meal_guidance.map((x, i) => (
                    <li key={i} className="flex gap-2 text-sm text-gray-700 leading-6"><span className="text-blue-500">•</span><span>{x}</span></li>
                  ))}
                </ul>
              </section>
            )}

            <p className="mt-6 text-xs text-gray-400 leading-5">
              이 안내는 시설 담당자가 확인한 내용입니다. 의료적 판단이 필요한 사항은 시설 간호 인력 또는 의료진과 상의해 주세요.
              이 링크는 {r.expires_on}까지 열람할 수 있습니다.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

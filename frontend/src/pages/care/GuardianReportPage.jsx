import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import axios from 'axios'
import { LogoMark } from '../../components/brand/Brand'
import ReportView from '../../components/care/ReportView'

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
    <div className="min-h-screen bg-navy-50/50">
      <div className="bg-navy-900 text-white">
        <div className="max-w-3xl mx-auto px-5 py-4 flex items-center gap-2.5">
          <LogoMark className="w-8 h-8" tone="white" />
          <span className="font-extrabold tracking-tight">Care<span className="text-sky-300">-</span>Eat</span>
          <span className="ml-auto text-[11px] text-navy-100/70">보호자 안내</span>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-5 py-8">
        {err && <div className="surface p-10 text-center text-slate-600">{err}</div>}
        {!err && !r && <div className="py-24 text-center text-muted">불러오는 중…</div>}
        {r && <ReportView r={r} />}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import ReportView from '../../components/care/ReportView'
import { errMsg } from '../../components/care/CareUI'

// 담당자용 상세 리포트 (척도 점수·우선순위 근거 포함)
export default function ResidentReportPage() {
  const { elderlyId } = useParams()
  const [r, setR] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get(`/care/residents/${elderlyId}/report`).then((res) => setR(res.data)).catch((e) => setErr(errMsg(e)))
  }, [elderlyId])

  return (
    <CareLayout
      title="상세 리포트"
      subtitle="조사 결과와 돌봄 계획을 한 장으로 정리했습니다."
      actions={
        <div className="flex gap-2">
          <Link to={`/care/residents/${elderlyId}`} className="btn-secondary text-sm">어르신 화면</Link>
          <button onClick={() => window.print()} className="btn-primary text-sm">인쇄 · PDF 저장</button>
        </div>
      }
    >
      {err && <p className="surface p-6 text-red-700">{err}</p>}
      {!err && !r && <div className="surface p-12 text-center text-muted">불러오는 중…</div>}
      {r && <ReportView r={r} />}
    </CareLayout>
  )
}

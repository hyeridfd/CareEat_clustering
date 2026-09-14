import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout, { Empty, SoonCard } from '../../components/care/CareLayout'
import { LevelPill, SOLUTION_STATUS, TypeBadge, errMsg, fmtDate } from '../../components/care/CareUI'

const TABS = [
  { key: 'care', label: '돌봄 솔루션' },
  { key: 'diet', label: '맞춤 식단 설계', soon: true },
  { key: 'program', label: '맞춤 프로그램', soon: true },
]
const FILTERS = [['all', '전체'], ['draft', '검토 필요'], ['approved', '승인됨'], ['sent', '발송됨']]

export default function SolutionsPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('care')
  const [data, setData] = useState(null)
  const [filter, setFilter] = useState('all')
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/care/solutions').then((r) => setData(r.data)).catch((e) => setErr(errMsg(e)))
  }, [])

  const rows = (data?.solutions || []).filter((s) => filter === 'all' || s.status === filter)

  return (
    <CareLayout title="솔루션" subtitle="유형과 위험 요인에 맞춘 돌봄 계획을 만들고 승인합니다.">
      <div className="flex flex-wrap gap-2 mb-5">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => setTab(t.key)}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-full text-sm font-semibold transition ${tab === t.key ? 'bg-navy-900 text-white' : 'bg-white border border-navy-100 text-navy-700 hover:border-navy-200'}`}>
            {t.label}{t.soon && <span className={`badge ${tab === t.key ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>준비 중</span>}
          </button>
        ))}
      </div>

      {tab === 'care' && (
        <>
          {err && <p className="mb-4 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            {[['검토 필요', data?.counts?.draft ?? '–', 'draft'], ['승인됨', data?.counts?.approved ?? '–', 'approved'],
              ['발송됨', data?.counts?.sent ?? '–', 'sent'], ['반려', data?.counts?.rejected ?? '–', 'rejected']].map(([l, v, k]) => (
              <button key={k} onClick={() => setFilter(filter === k ? 'all' : k)}
                className={`text-left rounded-2xl border bg-white p-4 transition ${filter === k ? 'border-navy-500 ring-2 ring-navy-100' : 'border-navy-100 hover:border-navy-200'}`}>
                <p className="text-xs font-medium text-muted">{l}</p>
                <p className="mt-1 text-2xl font-extrabold text-navy-900 tabular-nums">{v}</p>
              </button>
            ))}
          </div>

          <div className="flex gap-2 mb-4">
            {FILTERS.map(([k, l]) => (
              <button key={k} onClick={() => setFilter(k)}
                className={`px-3 py-1.5 rounded-full text-xs font-semibold ${filter === k ? 'bg-navy-600 text-white' : 'bg-white border border-navy-100 text-muted'}`}>{l}</button>
            ))}
          </div>

          {!data ? (
            <div className="surface p-12 text-center text-muted">불러오는 중…</div>
          ) : rows.length === 0 ? (
            <Empty icon="solution" title="솔루션이 없습니다"
              desc="진단 화면에서 어르신을 선택하고 '솔루션 초안 만들기'를 누르면 돌봄 계획이 만들어집니다."
              action={<button onClick={() => navigate('/care')} className="btn-primary">진단 화면으로</button>} />
          ) : (
            <div className="space-y-3">
              {rows.map((s) => (
                <button key={s.id} onClick={() => navigate(`/care/residents/${s.elderly_id}`)}
                  className="w-full text-left surface p-5 hover:border-navy-300 transition">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-navy-900">{s.display_name}</span>
                    <TypeBadge code={s.type_code} name={s.type_name} />
                    {s.priority_level && <LevelPill level={s.priority_level} />}
                    <span className={`badge ml-auto ${SOLUTION_STATUS[s.status]?.cls}`}>{SOLUTION_STATUS[s.status]?.label}</span>
                  </div>
                  <p className="mt-3 text-sm text-slate-600 leading-6 line-clamp-2">{s.summary}</p>
                  <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted">
                    <span>{fmtDate(s.created_at)}</span>
                    <span>{s.generator === 'rules' ? '규칙 기반' : s.generator}</span>
                    {s.flags > 0 && <span className="text-amber-700">자동 검증 수정 {s.flags}건</span>}
                  </div>
                </button>
              ))}
            </div>
          )}
        </>
      )}

      {tab === 'diet' && (
        <SoonCard title="맞춤 식단 설계"
          desc="유형과 질환, 씹기·삼키기 상태에 맞춰 한 달 식단과 개인별 배식량을 자동으로 설계하는 기능입니다. 별도 알고리즘을 개발 중이며, 완성되면 이 화면에서 바로 쓸 수 있습니다."
          bullets={['질환·유형별 금기·권장 식재료 반영', '영양 기준·예산·다양성 동시 최적화', '개인별 배식량과 대체 반찬 제안', '잔반 데이터로 다음 식단 자동 보정']} />
      )}

      {tab === 'program' && (
        <SoonCard title="맞춤 어르신 프로그램 추천"
          desc="유형과 기능 수준, 관심사에 맞는 놀이·인지·신체 활동 프로그램을 추천하는 기능입니다. 프로그램 목록과 난이도 기준을 정리하는 대로 열립니다."
          bullets={['기능 수준(K-MBI·인지)에 맞는 난이도', '유형별 추천 활동과 주의 사항', '참여 기록과 반응 기록', '식사·영양 개선과 함께 보는 변화']} />
      )}
    </CareLayout>
  )
}

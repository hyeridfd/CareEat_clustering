import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout, { Empty } from '../../components/care/CareLayout'
import { errMsg, fmtDate } from '../../components/care/CareUI'

const STATUS = {
  sent: { label: '발송', cls: 'bg-emerald-50 text-emerald-700' },
  previewed: { label: '테스트', cls: 'bg-slate-100 text-slate-600' },
  failed: { label: '실패', cls: 'bg-red-50 text-red-700' },
}

export default function CommunicationPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState('log')
  const [notis, setNotis] = useState(null)
  const [guardians, setGuardians] = useState(null)
  const [err, setErr] = useState('')
  const [openId, setOpenId] = useState(null)

  useEffect(() => {
    api.get('/care/notifications').then((r) => setNotis(r.data)).catch((e) => setErr(errMsg(e)))
    api.get('/care/guardians').then((r) => setGuardians(r.data)).catch(() => {})
  }, [])

  const consented = (guardians || []).filter((g) => g.consent_health_info).length

  return (
    <CareLayout title="보호자 소통" subtitle="승인된 돌봄 계획을 보호자에게 안내하고 기록을 남깁니다.">
      {err && <p className="mb-4 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        {[['보호자', guardians?.length ?? '–', '명'], ['수신 동의', consented, '명'],
          ['발송 성공', notis?.stats?.sent ?? '–', '건'], ['발송 실패', notis?.stats?.failed ?? '–', '건']].map(([l, v, u]) => (
          <div key={l} className="rounded-2xl border border-navy-100 bg-white p-4">
            <p className="text-xs font-medium text-muted">{l}</p>
            <p className="mt-1 text-2xl font-extrabold text-navy-900 tabular-nums">{v}<span className="ml-1 text-sm font-medium text-slate-400">{u}</span></p>
          </div>
        ))}
      </div>

      <div className="flex gap-2 mb-5">
        {[['log', '발송 기록'], ['guardians', '보호자 명단']].map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-4 py-2 rounded-full text-sm font-semibold ${tab === k ? 'bg-navy-900 text-white' : 'bg-white border border-navy-100 text-navy-700'}`}>{l}</button>
        ))}
      </div>

      {tab === 'log' && (
        !notis ? <div className="surface p-12 text-center text-muted">불러오는 중…</div>
          : notis.notifications.length === 0 ? (
            <Empty icon="connect" title="아직 보낸 안내가 없습니다"
              desc="어르신 화면에서 솔루션을 승인한 뒤 '보내기'를 누르면 보호자에게 안내 문자가 나갑니다."
              action={<button onClick={() => navigate('/care')} className="btn-primary">진단 화면으로</button>} />
          ) : (
            <div className="space-y-2">
              {notis.notifications.map((n) => (
                <div key={n.id} className="surface p-4">
                  <button onClick={() => setOpenId(openId === n.id ? null : n.id)} className="w-full text-left flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-navy-900">{n.display_name}</span>
                    <span className="text-xs text-muted">{n.guardian_name} · {n.phone}</span>
                    <span className={`badge ${STATUS[n.status]?.cls || 'bg-slate-100 text-slate-600'}`}>{STATUS[n.status]?.label || n.status}</span>
                    <span className="badge bg-navy-50 text-navy-700">{n.channel === 'sms' || n.mode === 'sms' ? '문자' : '알림톡'}</span>
                    <span className="ml-auto text-xs text-muted">{fmtDate(n.created_at)}</span>
                  </button>
                  {n.error && <p className="mt-2 text-xs text-red-700">실패 사유: {n.error}</p>}
                  {openId === n.id && (
                    <pre className="mt-3 whitespace-pre-wrap rounded-xl bg-navy-50/70 px-4 py-3 font-sans text-[13px] leading-6 text-navy-900">{n.rendered_text}</pre>
                  )}
                </div>
              ))}
            </div>
          )
      )}

      {tab === 'guardians' && (
        !guardians ? <div className="surface p-12 text-center text-muted">불러오는 중…</div>
          : guardians.length === 0 ? (
            <Empty icon="connect" title="등록된 보호자가 없습니다" desc="어르신 상세 화면에서 보호자를 등록하고 수신 동의를 받아 주세요." />
          ) : (
            <div className="surface overflow-x-auto">
              <table className="w-full text-sm min-w-[640px]">
                <thead>
                  <tr className="text-left text-xs text-muted border-b border-navy-100">
                    <th className="px-5 py-3">어르신</th><th className="px-2 py-3">보호자</th>
                    <th className="px-2 py-3">관계</th><th className="px-2 py-3">연락처</th>
                    <th className="px-5 py-3 text-right">수신 동의</th>
                  </tr>
                </thead>
                <tbody>
                  {guardians.map((g) => (
                    <tr key={g.id} onClick={() => navigate(`/care/residents/${g.elderly_id}`)}
                      className="border-b border-navy-50 last:border-0 hover:bg-navy-50/60 cursor-pointer">
                      <td className="px-5 py-3 font-semibold text-navy-900">{g.display_name}</td>
                      <td className="px-2 py-3">{g.name}</td>
                      <td className="px-2 py-3 text-muted">{g.relation || '-'}</td>
                      <td className="px-2 py-3 text-muted">{g.phone}</td>
                      <td className="px-5 py-3 text-right">
                        <span className={`badge ${g.consent_health_info ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>
                          {g.consent_health_info ? '동의' : '미동의'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
      )}
      <p className="mt-4 text-xs text-muted">수신 동의는 시설에서 보호자에게 직접 받은 경우에만 체크해 주세요. 동의하지 않은 보호자에게는 발송되지 않습니다.</p>
    </CareLayout>
  )
}

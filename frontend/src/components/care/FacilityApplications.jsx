import { useEffect, useState } from 'react'
import api from '../../lib/api'
import { errMsg, fmtDate } from './CareUI'

const STATUS = {
  pending: { label: '검토 대기', cls: 'bg-amber-50 text-amber-700' },
  approved: { label: '승인', cls: 'bg-emerald-50 text-emerald-700' },
  rejected: { label: '반려', cls: 'bg-slate-100 text-slate-500' },
}

// 운영 관리자: 시설 가입 신청 검토 → 승인 시 시설·담당자 계정 생성
export default function FacilityApplications() {
  const [rows, setRows] = useState([])
  const [filter, setFilter] = useState('pending')
  const [msg, setMsg] = useState(null)
  const [issued, setIssued] = useState(null)
  const [form, setForm] = useState({})

  const load = () => api.get('/admin/facility-applications').then((r) => setRows(r.data)).catch((e) => setMsg({ kind: 'error', text: errMsg(e) }))
  useEffect(() => { load() }, [])

  const approve = async (a) => {
    setMsg(null)
    try {
      const body = form[a.id] || {}
      const { data } = await api.post(`/admin/facility-applications/${a.id}/approve`, {
        staff_id: body.staff_id || undefined, password: body.password || undefined, note: body.note || undefined,
      })
      setIssued(data)
      load()
    } catch (e) { setMsg({ kind: 'error', text: errMsg(e) }) }
  }
  const reject = async (a) => {
    const note = window.prompt('반려 사유 (선택)') ?? undefined
    try { await api.post(`/admin/facility-applications/${a.id}/reject`, { note }); load() }
    catch (e) { setMsg({ kind: 'error', text: errMsg(e) }) }
  }

  const list = rows.filter((r) => filter === 'all' || r.status === filter)

  return (
    <div className="space-y-4">
      {msg && <p className={`text-sm rounded-xl px-4 py-3 ${msg.kind === 'error' ? 'bg-red-50 text-red-700' : 'bg-navy-50 text-navy-800'}`}>{msg.text}</p>}

      {issued && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5">
          <p className="font-bold text-emerald-900">계정을 발급했습니다 — 이 화면에서만 비밀번호를 확인할 수 있어요</p>
          <dl className="mt-3 grid sm:grid-cols-2 gap-2 text-sm text-emerald-900">
            <div>기관: <b>{issued.facility_name}</b> ({issued.nursing_home_id})</div>
            <div>담당자 ID: <b className="font-mono">{issued.staff_id}</b></div>
            <div>비밀번호: <b className="font-mono">{issued.password}</b></div>
            <div>연락처: {issued.manager_phone}</div>
          </dl>
          <button onClick={() => setIssued(null)} className="mt-4 btn-secondary text-sm">확인했습니다</button>
        </div>
      )}

      <div className="flex gap-2">
        {[['pending', '검토 대기'], ['approved', '승인'], ['rejected', '반려'], ['all', '전체']].map(([k, l]) => (
          <button key={k} onClick={() => setFilter(k)}
            className={`px-3 py-1.5 rounded-full text-xs font-semibold ${filter === k ? 'bg-navy-600 text-white' : 'bg-white border border-navy-100 text-muted'}`}>
            {l} {k !== 'all' && <span className="ml-1 tabular-nums">{rows.filter((r) => r.status === k).length}</span>}
          </button>
        ))}
      </div>

      {list.length === 0 && <p className="text-sm text-muted py-6">해당하는 신청이 없습니다.</p>}

      {list.map((a) => (
        <div key={a.id} className="rounded-2xl border border-navy-100 bg-white p-5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-navy-900">{a.facility_name}</span>
            <span className="text-xs text-muted">{a.facility_kind}</span>
            <span className={`badge ${STATUS[a.status]?.cls}`}>{STATUS[a.status]?.label}</span>
            <span className="ml-auto text-xs text-muted">{fmtDate(a.created_at)}</span>
          </div>
          <dl className="mt-3 grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm text-slate-600">
            <div>담당자: <b className="text-navy-900">{a.manager_name}</b> {a.manager_role && `(${a.manager_role})`}</div>
            <div>연락처: {a.manager_phone}{a.manager_email && ` · ${a.manager_email}`}</div>
            <div>기관 기호: {a.ltc_code || '-'}</div>
            <div>입소 인원: {a.resident_count ?? '-'}명</div>
            <div className="sm:col-span-2">주소: {a.address || '-'}</div>
            {a.message && <div className="sm:col-span-2 mt-1 rounded-xl bg-navy-50/70 px-4 py-2.5 text-[13px] leading-6">{a.message}</div>}
          </dl>

          {a.status === 'pending' ? (
            <div className="mt-4 grid sm:grid-cols-4 gap-2 items-end">
              <div className="sm:col-span-2">
                <label className="form-label text-xs">담당자 ID</label>
                <input className="form-input" placeholder={a.desired_staff_id || '자동 생성'}
                  onChange={(e) => setForm({ ...form, [a.id]: { ...form[a.id], staff_id: e.target.value } })} />
              </div>
              <div>
                <label className="form-label text-xs">비밀번호</label>
                <input className="form-input" placeholder="자동 생성"
                  onChange={(e) => setForm({ ...form, [a.id]: { ...form[a.id], password: e.target.value } })} />
              </div>
              <div className="flex gap-2">
                <button onClick={() => approve(a)} className="btn-primary text-sm flex-1">승인·계정 발급</button>
                <button onClick={() => reject(a)} className="btn-ghost text-sm">반려</button>
              </div>
            </div>
          ) : (
            <p className="mt-3 text-xs text-muted">
              {a.status === 'approved' ? `${a.nursing_home_id} · ${a.staff_id} 발급` : '반려됨'} {a.review_note && `· ${a.review_note}`}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

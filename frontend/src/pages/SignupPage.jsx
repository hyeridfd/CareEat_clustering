import { useState } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'
import { PublicFooter, PublicHeader } from '../components/brand/Brand'

const base = import.meta.env.VITE_API_URL || '/api'
const KINDS = ['노인요양시설(요양원)', '노인요양공동생활가정', '주야간보호센터', '노인복지주택', '기타']

const EMPTY = {
  facility_name: '', facility_kind: KINDS[0], ltc_code: '', address: '', resident_count: '',
  manager_name: '', manager_role: '', manager_phone: '', manager_email: '', desired_staff_id: '', message: '',
}

export default function SignupPage() {
  const [f, setF] = useState(EMPTY)
  const [agree, setAgree] = useState({ privacy: false, entrust: false })
  const [state, setState] = useState({ loading: false, error: '', done: false })
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    if (!agree.privacy || !agree.entrust) {
      setState({ ...state, error: '개인정보 수집·이용과 처리 위탁에 모두 동의해 주세요.' })
      return
    }
    setState({ loading: true, error: '', done: false })
    try {
      await axios.post(`${base}/public/facility-apply`, { ...f, resident_count: f.resident_count ? Number(f.resident_count) : null })
      setState({ loading: false, error: '', done: true })
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err) {
      const d = err.response?.data?.detail
      setState({ loading: false, done: false, error: typeof d === 'string' ? d : '신청을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.' })
    }
  }

  if (state.done) {
    return (
      <div className="min-h-screen flex flex-col bg-navy-50/40">
        <PublicHeader />
        <main className="flex-1 flex items-center justify-center px-5 py-20">
          <div className="surface max-w-lg w-full p-10 text-center">
            <span className="mx-auto flex w-14 h-14 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600">
              <svg viewBox="0 0 24 24" className="w-7 h-7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12.5l4.2 4.2L19 7" /></svg>
            </span>
            <h1 className="mt-6 text-2xl font-extrabold text-navy-900">가입 신청이 접수되었습니다</h1>
            <p className="mt-4 text-sm leading-7 text-slate-600">
              연구실에서 기관 정보를 확인한 뒤, 담당자 계정을 만들어 <b className="text-navy-900">{f.manager_phone || '알려 주신 연락처'}</b>로 안내드릴게요.
              보통 영업일 기준 1~3일이 걸립니다.
            </p>
            <div className="mt-8 flex justify-center gap-3">
              <Link to="/" className="btn-secondary">홈으로</Link>
              <Link to="/staff-login" className="btn-primary">담당자 로그인</Link>
            </div>
          </div>
        </main>
        <PublicFooter />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex flex-col bg-navy-50/40">
      <PublicHeader />
      <main className="flex-1 max-w-3xl w-full mx-auto px-5 py-14">
        <p className="eyebrow">시설 가입 신청</p>
        <h1 className="mt-3 text-3xl font-extrabold tracking-tight text-navy-900">Care-Eat 도입 신청</h1>
        <p className="mt-4 text-[15px] leading-7 text-slate-600">
          신청서를 보내 주시면 연구실에서 기관을 확인한 뒤 담당자 계정을 발급해 드립니다.
          계정은 신청하신 시설의 어르신 정보만 볼 수 있습니다.
        </p>

        <form onSubmit={submit} className="mt-8 space-y-6">
          <section className="surface p-6">
            <h2 className="text-sm font-bold text-navy-900 mb-4">기관 정보</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <div className="sm:col-span-2">
                <label className="form-label">기관명 *</label>
                <input className="form-input" value={f.facility_name} onChange={set('facility_name')} required placeholder="예: 헤리티지 실버케어 분당" />
              </div>
              <div>
                <label className="form-label">기관 유형 *</label>
                <select className="form-select" value={f.facility_kind} onChange={set('facility_kind')}>
                  {KINDS.map((k) => <option key={k}>{k}</option>)}
                </select>
              </div>
              <div>
                <label className="form-label">장기요양기관 기호</label>
                <input className="form-input" value={f.ltc_code} onChange={set('ltc_code')} placeholder="확인용 (선택)" />
              </div>
              <div className="sm:col-span-2">
                <label className="form-label">기관 주소</label>
                <input className="form-input" value={f.address} onChange={set('address')} placeholder="시·도 / 시·군·구까지만 적어도 됩니다" />
              </div>
              <div>
                <label className="form-label">입소 어르신 수</label>
                <input className="form-input" value={f.resident_count} onChange={set('resident_count')} inputMode="numeric" placeholder="예: 60" />
              </div>
            </div>
          </section>

          <section className="surface p-6">
            <h2 className="text-sm font-bold text-navy-900 mb-4">담당자 정보</h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="form-label">이름 *</label>
                <input className="form-input" value={f.manager_name} onChange={set('manager_name')} required />
              </div>
              <div>
                <label className="form-label">직책</label>
                <input className="form-input" value={f.manager_role} onChange={set('manager_role')} placeholder="예: 시설장, 사회복지사, 영양사" />
              </div>
              <div>
                <label className="form-label">연락처 *</label>
                <input className="form-input" value={f.manager_phone} onChange={set('manager_phone')} required inputMode="tel" placeholder="010-0000-0000" />
              </div>
              <div>
                <label className="form-label">이메일</label>
                <input type="email" className="form-input" value={f.manager_email} onChange={set('manager_email')} />
              </div>
              <div className="sm:col-span-2">
                <label className="form-label">희망 로그인 ID</label>
                <input className="form-input" value={f.desired_staff_id} onChange={set('desired_staff_id')} placeholder="영문·숫자 (예: heritage_kim)" />
                <p className="form-hint">비워 두시면 연구실에서 만들어 드립니다.</p>
              </div>
              <div className="sm:col-span-2">
                <label className="form-label">도입 목적·문의</label>
                <textarea rows={3} className="form-input" value={f.message} onChange={set('message')} placeholder="어떤 점이 필요하신지 적어 주시면 안내에 도움이 됩니다." />
              </div>
            </div>
          </section>

          <section className="surface p-6">
            <h2 className="text-sm font-bold text-navy-900 mb-4">동의</h2>
            <div className="space-y-3 text-sm">
              <label className="flex gap-3 items-start">
                <input type="checkbox" className="mt-1" checked={agree.privacy} onChange={(e) => setAgree({ ...agree, privacy: e.target.checked })} />
                <span className="text-slate-600 leading-6">
                  <b className="text-navy-900">[필수] 개인정보 수집·이용 동의</b><br />
                  신청 확인과 계정 발급 안내를 위해 담당자의 이름·연락처·이메일을 수집하며, 가입 절차 종료 후 1년간 보관 후 파기합니다.
                </span>
              </label>
              <label className="flex gap-3 items-start">
                <input type="checkbox" className="mt-1" checked={agree.entrust} onChange={(e) => setAgree({ ...agree, entrust: e.target.checked })} />
                <span className="text-slate-600 leading-6">
                  <b className="text-navy-900">[필수] 개인정보 처리 위탁 확인</b><br />
                  어르신의 건강·식사 정보에 대한 책임은 시설에 있으며, 연구실은 서비스 제공 범위에서만 이를 처리합니다.
                  어르신(또는 법정대리인)과 보호자의 동의는 시설에서 받아 보관합니다. 정식 위탁 계약은 승인 단계에서 별도로 체결합니다.
                </span>
              </label>
            </div>
          </section>

          {state.error && <p className="rounded-xl bg-red-50 text-red-700 text-sm px-4 py-3">{state.error}</p>}

          <div className="flex flex-wrap items-center gap-3">
            <button className="btn-primary btn-lg" disabled={state.loading}>{state.loading ? '전송 중…' : '가입 신청 보내기'}</button>
            <Link to="/" className="btn-ghost">취소</Link>
          </div>
        </form>
      </main>
      <PublicFooter />
    </div>
  )
}

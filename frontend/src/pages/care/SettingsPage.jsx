import { useEffect, useState } from 'react'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { errMsg, fmtDate } from '../../components/care/CareUI'

export default function SettingsPage() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    api.get('/care/facility').then((r) => setD(r.data)).catch((e) => setErr(errMsg(e)))
  }, [])

  if (err) return <CareLayout title="설정"><p className="surface p-6 text-red-700">{err}</p></CareLayout>
  if (!d) return <CareLayout title="설정"><div className="surface p-12 text-center text-muted">불러오는 중…</div></CareLayout>

  return (
    <CareLayout title="설정" subtitle="시설 정보와 계정, 사용 중인 유형 모델을 확인합니다.">
      <div className="grid lg:grid-cols-2 gap-5">
        <section className="surface p-6">
          <h2 className="text-sm font-bold text-navy-900 mb-4">시설 정보</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-muted">기관명</dt><dd className="font-semibold text-navy-900">{d.facility.name || '-'}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">기관 코드</dt><dd className="font-mono text-navy-900">{d.facility.id}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">등록 어르신</dt><dd className="font-semibold text-navy-900">{d.resident_count}명</dd></div>
          </dl>
          <p className="mt-4 text-xs text-muted">기관 정보 변경이 필요하면 연구실로 문의해 주세요.</p>
        </section>

        <section className="surface p-6">
          <h2 className="text-sm font-bold text-navy-900 mb-4">내 계정</h2>
          <dl className="space-y-3 text-sm">
            <div className="flex justify-between gap-4"><dt className="text-muted">이름</dt><dd className="font-semibold text-navy-900">{d.me.name}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">로그인 ID</dt><dd className="font-mono text-navy-900">{d.me.staff_id}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted">권한</dt><dd className="text-navy-900">{d.me.role === 'manager' ? '시설 관리자' : '담당자'}</dd></div>
          </dl>
          <p className="mt-4 text-xs text-muted">비밀번호 변경이나 담당자 추가는 연구실에 요청해 주세요.</p>
        </section>

        <section className="surface p-6">
          <h2 className="text-sm font-bold text-navy-900 mb-4">담당자 계정</h2>
          <ul className="divide-y divide-navy-50">
            {d.staff.map((s) => (
              <li key={s.id} className="py-2.5 flex items-center justify-between gap-3 text-sm">
                <span>
                  <span className="font-semibold text-navy-900">{s.name}</span>
                  <span className="ml-2 text-xs font-mono text-muted">{s.id}</span>
                </span>
                <span className={`badge ${s.is_active === false ? 'bg-slate-100 text-slate-500' : 'bg-emerald-50 text-emerald-700'}`}>
                  {s.is_active === false ? '중지' : s.role === 'manager' ? '시설 관리자' : '담당자'}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="surface p-6">
          <h2 className="text-sm font-bold text-navy-900 mb-4">유형 모델</h2>
          {d.model?.error ? (
            <p className="text-sm text-amber-700">{d.model.error}</p>
          ) : (
            <>
              <p className="text-sm text-muted">현재 버전 <span className="font-mono font-semibold text-navy-900">{d.model.version}</span> · 유형 {d.model.k}개</p>
              <ul className="mt-4 space-y-2">
                {d.model.types.map((t) => (
                  <li key={t.code} className="rounded-xl bg-navy-50/70 px-4 py-3">
                    <p className="text-sm font-bold text-navy-900">{t.code} · {t.name}</p>
                    <p className="text-xs text-muted mt-0.5">보호자 안내 표현: {t.guardian_label}</p>
                    {t.description && <p className="text-xs text-slate-500 mt-1 leading-5">{t.description}</p>}
                  </li>
                ))}
              </ul>
              <p className="mt-4 text-xs text-muted">데이터가 쌓이면 연구실에서 모델을 갱신하며, 유형의 의미는 그대로 유지됩니다.</p>
            </>
          )}
        </section>
      </div>
      <p className="mt-6 text-xs text-muted">
        어르신의 건강정보는 시설의 관리 책임 아래 처리되며, 연구실은 서비스 제공 범위에서만 데이터를 다룹니다.
        문의: 서울대학교 정밀식의약솔루션 연구실 (PFML)
      </p>
    </CareLayout>
  )
}

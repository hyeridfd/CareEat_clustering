import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import useAuthStore from '../../lib/authStore'
import { LogoMark } from '../brand/Brand'

const NAV = [
  { to: '/care/records', label: '기록', desc: '어르신·조사 현황', icon: 'record' },
  { to: '/care', label: '진단', desc: '유형·돌봄 우선순위', icon: 'diagnose', exact: true },
  { to: '/care/solutions', label: '솔루션', desc: '돌봄 계획·식단·프로그램', icon: 'solution' },
  { to: '/care/news', label: '동향', desc: '노인·돌봄 뉴스 브리핑', icon: 'news' },
  { to: '/care/connect', label: '소통', desc: '보호자 안내·발송 기록', icon: 'connect' },
  { to: '/care/settings', label: '설정', desc: '시설·계정', icon: 'settings' },
]

export function NavIcon({ name, className = 'w-[18px] h-[18px]' }) {
  const p = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }
  const shapes = {
    record: <><rect x="4" y="3" width="16" height="18" rx="3" {...p} /><path d="M8 8h8M8 12h8M8 16h5" {...p} /></>,
    diagnose: <><circle cx="8" cy="9" r="3" {...p} /><circle cx="16" cy="15" r="3" {...p} /><path d="M11 9h3M10 15H7" {...p} /></>,
    solution: <><path d="M12 3a6 6 0 0 0-3 11.2V17h6v-2.8A6 6 0 0 0 12 3z" {...p} /><path d="M10 20h4" {...p} /></>,
    news: <><path d="M4 5h11v14H6a2 2 0 0 1-2-2V5z" {...p} /><path d="M15 9h3a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2" {...p} /><path d="M7 8.5h5M7 12h5M7 15.5h3" {...p} /></>,
    connect: <><path d="M4 7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H9l-5 4V7z" {...p} /></>,
    settings: <><circle cx="12" cy="12" r="3.2" {...p} /><path d="M12 3v2.2M12 18.8V21M21 12h-2.2M5.2 12H3M18.4 5.6l-1.6 1.6M7.2 16.8l-1.6 1.6M18.4 18.4l-1.6-1.6M7.2 7.2L5.6 5.6" {...p} /></>,
  }
  return <svg viewBox="0 0 24 24" className={className}>{shapes[name]}</svg>
}

export default function CareLayout({ children, title, subtitle, actions }) {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const [facility, setFacility] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    api.get('/care/facility').then((r) => setFacility(r.data)).catch(() => {})
  }, [])
  useEffect(() => setOpen(false), [pathname])

  const isActive = (n) => (n.exact ? pathname === n.to : pathname.startsWith(n.to))
  const facilityName = facility?.facility?.name || user?.nursing_home_name || ''

  return (
    <div className="min-h-screen bg-navy-50/40 lg:flex">
      {/* 데스크톱 사이드바 */}
      <aside className="hidden lg:flex lg:flex-col w-64 shrink-0 bg-navy-900 text-white">
        <div className="px-5 py-5 border-b border-white/10">
          <Link to="/care" className="flex items-center gap-2.5">
            <LogoMark className="w-9 h-9" tone="white" />
            <span className="leading-tight">
              <span className="block text-[17px] font-extrabold tracking-tight">Care<span className="text-sky-300">-</span>Eat</span>
              <span className="block text-[10px] text-navy-100/70">돌봄 관리</span>
            </span>
          </Link>
        </div>
        <div className="px-5 py-4 border-b border-white/10">
          <p className="text-[11px] text-navy-100/60">이용 기관</p>
          <p className="mt-0.5 text-sm font-bold truncate">{facilityName || '—'}</p>
          {facility && <p className="mt-1 text-[11px] text-navy-100/60">어르신 {facility.resident_count}명</p>}
        </div>
        <nav className="flex-1 px-3 py-4 space-y-1">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to}
              className={`flex items-start gap-3 rounded-xl px-3 py-2.5 transition ${isActive(n) ? 'bg-white/12 text-white' : 'text-navy-100/75 hover:bg-white/[0.07] hover:text-white'}`}>
              <span className={isActive(n) ? 'text-sky-300 mt-0.5' : 'mt-0.5'}><NavIcon name={n.icon} /></span>
              <span>
                <span className="block text-sm font-semibold">{n.label}</span>
                <span className="block text-[11px] text-navy-100/55">{n.desc}</span>
              </span>
            </Link>
          ))}
        </nav>
        <div className="px-5 py-4 border-t border-white/10 text-[11px] text-navy-100/60">
          <p className="text-white text-sm font-semibold">{user?.staff_name}님</p>
          {facility?.model?.version && <p className="mt-1">유형 모델 {facility.model.version}</p>}
          <button onClick={() => { logout(); navigate('/staff-login') }} className="mt-3 text-navy-100/70 hover:text-white">로그아웃</button>
        </div>
      </aside>

      {/* 모바일 상단바 */}
      <div className="lg:hidden sticky top-0 z-30 bg-navy-900 text-white">
        <div className="flex items-center justify-between px-4 h-14">
          <Link to="/care" className="flex items-center gap-2">
            <LogoMark className="w-8 h-8" tone="white" />
            <span className="font-extrabold tracking-tight">Care<span className="text-sky-300">-</span>Eat</span>
          </Link>
          <button onClick={() => setOpen(!open)} className="p-2 -mr-2" aria-label="메뉴">
            <svg viewBox="0 0 24 24" className="w-6 h-6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              {open ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
        </div>
        {open && (
          <nav className="px-3 pb-3 space-y-1">
            {NAV.map((n) => (
              <Link key={n.to} to={n.to}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm ${isActive(n) ? 'bg-white/12 font-semibold' : 'text-navy-100/80'}`}>
                <NavIcon name={n.icon} />{n.label}
                <span className="text-[11px] text-navy-100/50">{n.desc}</span>
              </Link>
            ))}
            <button onClick={() => { logout(); navigate('/staff-login') }} className="w-full text-left rounded-xl px-3 py-2.5 text-sm text-navy-100/70">로그아웃</button>
          </nav>
        )}
      </div>

      {/* 본문 */}
      <div className="flex-1 min-w-0">
        <header className="bg-white border-b border-navy-100">
          <div className="max-w-6xl mx-auto px-5 py-5 flex flex-wrap items-end justify-between gap-3">
            <div>
              <p className="text-xs font-semibold text-navy-500">{facilityName}</p>
              <h1 className="mt-1 text-xl font-extrabold tracking-tight text-navy-900">{title}</h1>
              {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
            </div>
            {actions}
          </div>
        </header>
        <main className="max-w-6xl mx-auto px-5 py-6">{children}</main>
      </div>
    </div>
  )
}

export function Empty({ icon = 'record', title, desc, action }) {
  return (
    <div className="surface p-12 text-center">
      <span className="mx-auto flex w-12 h-12 items-center justify-center rounded-2xl bg-navy-50 text-navy-400"><NavIcon name={icon} className="w-6 h-6" /></span>
      <p className="mt-4 font-bold text-navy-900">{title}</p>
      {desc && <p className="mt-2 text-sm text-muted max-w-md mx-auto leading-6">{desc}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  )
}

export function SoonCard({ title, desc, bullets = [] }) {
  return (
    <div className="surface p-6 relative overflow-hidden">
      <span className="badge-soon absolute right-5 top-5">준비 중</span>
      <p className="font-bold text-navy-900">{title}</p>
      <p className="mt-2 text-sm leading-6 text-muted max-w-lg">{desc}</p>
      {bullets.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {bullets.map((b) => (
            <li key={b} className="flex items-center gap-2 text-sm text-slate-400">
              <span className="w-1.5 h-1.5 rounded-full bg-navy-200" />{b}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

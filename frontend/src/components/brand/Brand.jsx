import { Link } from 'react-router-dom'
import pfmlLogo from '../../assets/pfml-logo.png'
import careEatMark from '../../assets/care-eat-mark.png'

// Care-Eat 로고 마크: 손과 포크가 맞잡은 하트
// 로고 자체가 남색을 쓰므로 어두운 배경에서는 흰 타일 위에 올린다.
export function LogoMark({ className = 'w-9 h-9', tone = 'navy' }) {
  const img = (
    <img
      src={careEatMark}
      alt=""
      aria-hidden
      width={256}
      height={256}
      className={tone === 'white' ? 'h-[82%] w-[82%] object-contain' : 'h-full w-full object-contain'}
    />
  )
  if (tone === 'white') {
    return (
      <span className={`${className} shrink-0 flex items-center justify-center rounded-xl bg-white`}>
        {img}
      </span>
    )
  }
  return <span className={`${className} shrink-0 inline-flex`}>{img}</span>
}

export function Wordmark({ tone = 'navy', sub = true }) {
  const text = tone === 'white' ? 'text-white' : 'text-navy-900'
  const subText = tone === 'white' ? 'text-navy-100/80' : 'text-muted'
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark tone={tone} />
      <span className="leading-tight">
        <span className={`block text-[19px] font-extrabold tracking-tight ${text}`}>
          Care<span className={tone === 'white' ? 'text-sky-300' : 'text-navy-500'}>-</span>Eat
        </span>
        {sub && <span className={`block text-[10px] font-medium ${subText}`}>요양시설 건강·식사 돌봄 플랫폼</span>}
      </span>
    </span>
  )
}

export function BrandLink({ to = '/', tone = 'navy', sub = true }) {
  return <Link to={to} className="inline-flex"><Wordmark tone={tone} sub={sub} /></Link>
}

// PFML 연구실 로고 (운영 주체 표기용). 어두운 배경에서는 흰색으로 반전해 사용
// flex 컨테이너 안에서는 align-items 기본값(stretch) 때문에 img 가 가로로 늘어난다.
// self-start 로 늘어남을 막고, object-contain 으로 어떤 경우에도 비율을 지킨다.
export function PfmlLogo({ className = 'h-9', tone = 'navy' }) {
  return (
    <img
      src={pfmlLogo}
      alt="서울대학교 정밀식의약솔루션 연구실 PFML"
      width={480}
      height={208}
      className={`${className} w-auto max-w-full shrink-0 self-start object-contain ${tone === 'white' ? 'brightness-0 invert opacity-95' : ''}`}
    />
  )
}

export function Lab({ className = '', tone = 'navy', logo = false }) {
  const c = tone === 'white' ? 'text-navy-100/80' : 'text-muted'
  if (logo) {
    return (
      <span className={`flex flex-col items-start gap-2 ${className}`}>
        <PfmlLogo tone={tone} className="h-12" />
        <span className={`text-xs leading-relaxed ${c}`}>서울대학교 농생명공학부 정밀식의약솔루션 연구실</span>
      </span>
    )
  }
  return (
    <span className={`text-xs leading-relaxed ${c} ${className}`}>
      서울대학교 농생명공학부 정밀식의약솔루션 연구실 (PFML)
    </span>
  )
}

export function PublicFooter() {
  return (
    <footer className="bg-navy-900 text-navy-100">
      <div className="max-w-6xl mx-auto px-5 py-12 grid gap-8 md:grid-cols-3">
        <div>
          <Wordmark tone="white" />
          <p className="mt-4 text-sm text-navy-100/75 leading-relaxed max-w-xs">
            어르신의 건강·식사 기록을 유형으로 진단하고, 돌봄 솔루션과 보호자 소통까지 잇는 요양시설 플랫폼입니다.
          </p>
        </div>
        <div className="text-sm">
          <p className="font-semibold text-white mb-3">서비스</p>
          <ul className="space-y-2 text-navy-100/75">
            <li><a href="/#record" className="hover:text-white">기록</a></li>
            <li><a href="/#diagnose" className="hover:text-white">진단</a></li>
            <li><a href="/#solution" className="hover:text-white">솔루션</a></li>
            <li><a href="/#connect" className="hover:text-white">보호자 소통</a></li>
          </ul>
        </div>
        <div className="text-sm">
          <p className="font-semibold text-white mb-3">운영</p>
          <PfmlLogo tone="white" className="h-9 mb-3" />
          <Lab tone="white" />
          <p className="mt-3 text-navy-100/75">글로벌 블루푸드 미래리더 양성 프로젝트</p>
          <p className="mt-4 text-navy-100/60 text-xs">© {new Date().getFullYear()} PFML, Seoul National University.</p>
        </div>
      </div>
    </footer>
  )
}

export function PublicHeader({ active = '' }) {
  const nav = [
    { id: 'record', label: '기록' },
    { id: 'diagnose', label: '진단' },
    { id: 'solution', label: '솔루션' },
    { id: 'connect', label: '보호자 소통' },
  ]
  return (
    <header className="sticky top-0 z-40 bg-white/90 backdrop-blur border-b border-navy-100">
      <div className="max-w-6xl mx-auto px-5 h-16 flex items-center justify-between gap-4">
        <BrandLink sub={false} />
        <nav className="hidden md:flex items-center gap-7 text-sm font-medium text-navy-900/80">
          {nav.map((n) => (
            <a key={n.id} href={`/#${n.id}`} className={`hover:text-navy-600 ${active === n.id ? 'text-navy-600' : ''}`}>{n.label}</a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <Link to="/staff-login" className="btn-ghost text-sm">로그인</Link>
          <Link to="/signup" className="btn-primary text-sm">시설 가입 신청</Link>
        </div>
      </div>
    </header>
  )
}

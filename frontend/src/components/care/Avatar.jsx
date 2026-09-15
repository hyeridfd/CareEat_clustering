// 어르신 아바타 — 사진을 보관하지 않고 이름·ID 로 일정한 모양을 만든다.
// 같은 어르신은 언제 봐도 같은 색이 나오도록 ID 해시로 색을 고른다.
const TINTS = [
  { bg: 'bg-navy-100', fg: 'text-navy-700', ring: 'ring-navy-200' },
  { bg: 'bg-sky-100', fg: 'text-sky-600', ring: 'ring-sky-200' },
  { bg: 'bg-teal-100', fg: 'text-teal-700', ring: 'ring-teal-200' },
  { bg: 'bg-amber-100', fg: 'text-amber-700', ring: 'ring-amber-200' },
  { bg: 'bg-violet-100', fg: 'text-violet-700', ring: 'ring-violet-200' },
  { bg: 'bg-rose-100', fg: 'text-rose-700', ring: 'ring-rose-200' },
]

function pick(seed = '') {
  let h = 0
  for (let i = 0; i < seed.length; i += 1) h = (h * 31 + seed.charCodeAt(i)) >>> 0
  return TINTS[h % TINTS.length]
}

// 한글은 성을 빼고 이름 첫 글자, 영문은 이니셜 두 자
function initial(name = '') {
  const n = name.trim()
  if (!n) return '·'
  if (/^[가-힣]/.test(n)) return n.length >= 2 ? n.slice(1, 2) : n.slice(0, 1)
  return n.split(/\s+/).slice(0, 2).map((w) => w[0]).join('').toUpperCase()
}

export default function Avatar({ name, id, size = 'md', className = '' }) {
  const t = pick(id || name || '')
  const s = {
    sm: 'w-9 h-9 text-sm',
    md: 'w-14 h-14 text-xl',
    lg: 'w-20 h-20 text-3xl',
  }[size]
  return (
    <span
      aria-hidden
      className={`${s} ${t.bg} ${t.fg} ${t.ring} ${className} shrink-0 inline-flex items-center justify-center rounded-full ring-1 font-bold select-none`}
    >
      {initial(name)}
    </span>
  )
}

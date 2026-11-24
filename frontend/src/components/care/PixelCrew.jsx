/* [2026-11-24] AI 영양사 · AI 간호사 픽셀 캐릭터
   - 왼쪽 절반(9칸, 마지막 칸이 가운데)만 그리고 좌우 대칭으로 펼친다 → 17×26 픽셀
   - CrewAvatar: 검증 결과 옆 작은 얼굴 / CrewWalk: 검증 중 화면을 돌아다니는 로딩 */
import { useEffect, useState } from 'react'

const PAL = {
  K: '#3b2b2e', H: '#1f1a1f', h: '#4a3f4c', S: '#ffe1cc', s: '#f5c6a8', E: '#2a1d1a', e: '#ffffff',
  P: '#ffb1b9', M: '#d95d6a', W: '#ffffff', w: '#e3e7ef', R: '#ef4b55', n: '#ffd3df', G: '#86d0a8',
  g: '#4ea67a', B: '#eadfcd', Y: '#f6c445', U: '#8dbdeb', u: '#5f93cf', y: '#9aa3b2', q: '#5b6472',
}
const mirror = (half) => half + half.slice(0, 8).split('').reverse().join('')

const FACE = [
  '.KHHHHHHH', '.KHHHHHHH', '.KHHHHHHH', '.KHHSHHSS', '.KHSSEESS',
  '.KHSSeESS', '.KHSSEESS', '.KHSPPSSM', '.KHHSSSSS', '..KHHKSSS', '..KHHKKWW',
]
// 다리: 왼쪽 절반만(대칭) · 걷는 두 번째 프레임은 비대칭이라 17칸 전체로
const legs = (c) => ({
  a: [`....K${c}K..`, `....K${c}K..`, '...KBBK..'].map(mirror),
  b: [`....K${c}K...K${c}K....`, `...KBBK...K${c}K....`, '..........KBBK...'],
})

const SPRITES = {
  // AI 간호사 — 간호사 모자(그대로) · 파란 반팔 상의 · 파란 긴바지
  nurse: {
    name: 'AI 간호사',
    top: ['.....KKKK', '....KWWWW', '....KWWWR', '....KWWRR', '...KKWWWR', '..KHHKKKK'],
    body: ['..KHKUUUS', '..KHKUUUU', '.KUKUUUUU', '.KSKUUUUU', '...KUUUUU', '...KuuuuK'],
    legs: legs('u'),
  },
  // AI 영양사 — 모자 없이 단정한 머리 · 흰 가운(가운데 여밈) · 짙은 바지
  nutritionist: {
    name: 'AI 영양사',
    top: ['.....KKKK', '...KKHHHH', '..KHHHHHH'],
    body: ['..KHKWwWS', '..KHKWWwW', '.KWKWWWWw', '.KSKWwWWw', '...KWwWWw', '...KWWWWw'],
    legs: legs('q'),
  },
}

function rows(kind, frame) {
  const sp = SPRITES[kind]
  return [...sp.top, ...FACE, ...sp.body].map(mirror).concat(frame ? sp.legs.b : sp.legs.a)
}

const TAG_STYLE = {   // 명찰: 가운·상의 위에서 잘 보이는 색
  nurse: 'bg-white text-sky-700 ring-sky-300',
  nutritionist: 'bg-emerald-600 text-white ring-emerald-700',
}

export function PixelSprite({ kind = 'nurse', scale = 3, frame = 0, className = '', nametag = false }) {
  const rs = rows(kind, frame)
  const w = 17, h = rs.length
  const svg = (
    <svg width={w * scale} height={h * scale} viewBox={`0 0 ${w} ${h}`} shapeRendering="crispEdges" className={nametag ? '' : className}
      role="img" aria-label={SPRITES[kind].name}>
      {rs.flatMap((r, y) => r.split('').map((c, x) => (c !== '.' && PAL[c]
        ? <rect key={`${x}-${y}`} x={x} y={y} width="1.02" height="1.02" fill={PAL[c]} /> : null)))}
    </svg>
  )
  if (!nametag) return svg
  const chest = (SPRITES[kind].top.length + FACE.length + 2) * scale   // 상의 세 번째 줄 높이
  return (
    <span className={`relative inline-block ${className}`}>
      {svg}
      <span className={`absolute left-1/2 -translate-x-1/2 whitespace-nowrap rounded-[3px] px-1 py-px font-bold leading-none ring-1 shadow-sm ${TAG_STYLE[kind]}`}
        style={{ top: chest, fontSize: Math.max(9, Math.round(scale * 2.5)), letterSpacing: "-0.02em" }}>
        {SPRITES[kind].name}
      </span>
    </span>
  )
}

export function CrewAvatar({ kind, size = 2, label = true }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block rounded-lg bg-white ring-1 ring-gray-200 p-0.5"><PixelSprite kind={kind} scale={size} /></span>
      {label && <span className="text-xs font-bold text-gray-800">{SPRITES[kind].name}</span>}
    </span>
  )
}

const LINES = {
  nurse: ['초안을 읽는 중…', '삼킴·안전 조치 확인 중', '관찰 항목·주기 확인 중', '보호자 안내문 읽는 중', '질환 간 충돌 확인 중'],
  nutritionist: ['식사 지침 확인 중…', '나트륨·당류 지침 대조 중', '음식·양·시점이 구체적인지 보는 중', '잔반 음식군 대응 확인 중', '근거 문헌 대조 중'],
}

/* 로딩 — 캐릭터가 좌우로 걸어 다니며 하는 일을 말풍선으로
   crew: 등장 캐릭터 · lines: {캐릭터: [말풍선 문구]} (없으면 기본 문구) · title: 위 제목 */
export function CrewWalk({ note, crew = ['nutritionist', 'nurse'], lines, title }) {
  const [t, setT] = useState(0)
  useEffect(() => { const id = setInterval(() => setT((x) => x + 1), 220); return () => clearInterval(id) }, [])
  const frame = t % 2
  const L = { ...LINES, ...(lines || {}) }
  const line = (k, off) => { const ls = L[k] || ['…']; return ls[Math.floor((t + off) / 18) % ls.length] }
  const solo = crew.length === 1
  return (
    <div className="mb-4 rounded-xl bg-gradient-to-b from-sky-50 to-emerald-50/60 ring-1 ring-sky-100 px-3 pt-3 pb-1">
      <style>{`
        @keyframes crewWalkA { 0%{left:2%} 50%{left:calc(55% - 80px)} 100%{left:2%} }
        @keyframes crewWalkB { 0%{left:calc(98% - 80px)} 50%{left:45%} 100%{left:calc(98% - 80px)} }
        @keyframes crewWalkSolo { 0%{left:2%} 50%{left:calc(98% - 80px)} 100%{left:2%} }
        @keyframes crewBob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-3px)} }
      `}</style>
      <p className="text-xs font-semibold text-sky-900">{title || 'AI 영양사·AI 간호사가 리포트를 검증하고 있어요'}</p>
      {note && <p className="text-[11px] text-gray-500">{note}</p>}
      <div className="relative h-[150px] overflow-hidden">
        {crew.map((k, i) => (
          <div key={k} className="absolute bottom-1" style={{ animation: `${solo ? 'crewWalkSolo 12s' : i === 0 ? 'crewWalkA 9s' : 'crewWalkB 9s'} ease-in-out infinite` }}>
            <div className="mb-1 -ml-6 w-[120px] rounded-lg bg-white px-2 py-1 text-center text-[10px] leading-4 text-gray-700 shadow-sm ring-1 ring-gray-200">
              {line(k, i * 9)}
            </div>
            <div className="flex flex-col items-center" style={{ animation: 'crewBob .44s steps(2) infinite' }}>
              <PixelSprite kind={k} scale={4} frame={(frame + i) % 2} nametag />
            </div>
          </div>
        ))}
        <div className="absolute inset-x-0 bottom-0 h-1 rounded-full bg-emerald-200/70" />
      </div>
    </div>
  )
}

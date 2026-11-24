/* [2026-11-24] AI 영양사 · AI 간호사 픽셀 캐릭터
   - 왼쪽 절반(9칸, 마지막 칸이 가운데)만 그리고 좌우 대칭으로 펼친다 → 17×26 픽셀
   - CrewAvatar: 검증 결과 옆 작은 얼굴 / CrewWalk: 검증 중 화면을 돌아다니는 로딩 */
import { useEffect, useState } from 'react'

const PAL = {
  K: '#3b2b2e', H: '#1f1a1f', h: '#4a3f4c', S: '#ffe1cc', s: '#f5c6a8', E: '#2a1d1a', e: '#ffffff',
  P: '#ffb1b9', M: '#d95d6a', W: '#ffffff', w: '#e3e7ef', R: '#ef4b55', n: '#ffd3df', G: '#86d0a8',
  g: '#4ea67a', B: '#eadfcd', Y: '#f6c445',
}
const mirror = (half) => half + half.slice(0, 8).split('').reverse().join('')

const FACE = [
  '.KHHHHHHH', '.KHHHHHHH', '.KHHHHHHH', '.KHHSHHSS', '.KHSSEESS',
  '.KHSSeESS', '.KHSSEESS', '.KHSPPSSM', '.KHHSSSSS', '..KHHKSSS', '..KHHKKWW',
]
const LEGS_A = ['....KSK..', '....KWK..', '...KBBK..'].map(mirror)
const LEGS_B = ['....KSK...KSK....', '...KBBK...KWK....', '..........KBBK...']

const SPRITES = {
  nurse: {
    name: 'AI 간호사',
    top: ['.....KKKK', '....KWWWW', '....KWWWR', '....KWWRR', '...KKWWWR', '..KHHKKKK'],
    body: ['..KHKnnnW', '..KHKnnnn', '.KSKnnnnn', '.KKKnnnnn', '...Knnnnn', '...KKKKKK'],
  },
  nutritionist: {
    name: 'AI 영양사',
    top: ['....KKK.K', '...KWWWKW', '..KWWWWWW', '..KWWWWWW', '...KwwwWW', '..KHKKKKK'],
    body: ['..KHKwGGG', '..KHKwGgG', '.KSKwGGGG', '.KKKwGGGG', '...KwGGGG', '...KKKKKK'],
  },
}

function rows(kind, frame) {
  const sp = SPRITES[kind]
  return [...sp.top, ...FACE, ...sp.body].map(mirror).concat(frame ? LEGS_B : LEGS_A)
}

export function PixelSprite({ kind = 'nurse', scale = 3, frame = 0, className = '' }) {
  const rs = rows(kind, frame)
  const w = 17, h = rs.length
  return (
    <svg width={w * scale} height={h * scale} viewBox={`0 0 ${w} ${h}`} shapeRendering="crispEdges" className={className}
      role="img" aria-label={SPRITES[kind].name}>
      {rs.flatMap((r, y) => r.split('').map((c, x) => (c !== '.' && PAL[c]
        ? <rect key={`${x}-${y}`} x={x} y={y} width="1.02" height="1.02" fill={PAL[c]} /> : null)))}
    </svg>
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

/* 검증 중 로딩 — 두 캐릭터가 좌우로 걸어 다니며 하는 일을 말풍선으로 */
export function CrewWalk({ note }) {
  const [t, setT] = useState(0)
  useEffect(() => { const id = setInterval(() => setT((x) => x + 1), 220); return () => clearInterval(id) }, [])
  const frame = t % 2
  const line = (k, off) => LINES[k][Math.floor((t + off) / 18) % LINES[k].length]
  return (
    <div className="mb-4 rounded-xl bg-gradient-to-b from-sky-50 to-emerald-50/60 ring-1 ring-sky-100 px-3 pt-3 pb-1">
      <style>{`
        @keyframes crewWalkA { 0%{left:2%} 50%{left:calc(55% - 60px)} 100%{left:2%} }
        @keyframes crewWalkB { 0%{left:calc(98% - 60px)} 50%{left:45%} 100%{left:calc(98% - 60px)} }
        @keyframes crewBob { 0%,100%{transform:translateY(0)} 50%{transform:translateY(-3px)} }
      `}</style>
      <p className="text-xs font-semibold text-sky-900">AI 영양사·AI 간호사가 리포트를 검증하고 있어요</p>
      {note && <p className="text-[11px] text-gray-500">{note}</p>}
      <div className="relative h-[118px] overflow-hidden">
        {[['nutritionist', 'crewWalkA', 0], ['nurse', 'crewWalkB', 9]].map(([k, anim, off]) => (
          <div key={k} className="absolute bottom-1" style={{ animation: `${anim} 9s ease-in-out infinite` }}>
            <div className="mb-1 -ml-6 w-[120px] rounded-lg bg-white px-2 py-1 text-center text-[10px] leading-4 text-gray-700 shadow-sm ring-1 ring-gray-200">
              {line(k, off)}
            </div>
            <div className="flex flex-col items-center" style={{ animation: 'crewBob .44s steps(2) infinite' }}>
              <PixelSprite kind={k} scale={3} frame={(frame + (k === 'nurse' ? 1 : 0)) % 2} />
            </div>
          </div>
        ))}
        <div className="absolute inset-x-0 bottom-0 h-1 rounded-full bg-emerald-200/70" />
      </div>
    </div>
  )
}

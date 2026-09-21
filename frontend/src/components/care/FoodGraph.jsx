import { useEffect, useMemo, useState } from 'react'
import api from '../../lib/api'
import { errMsg } from './CareUI'

/* 식품·메뉴 그래프 — 메뉴 뜯어보기(방사형) / 추천 근거 경로(질환→영양소→재료→메뉴)
   의존성 없이 SVG로 그린다. 노드 종류 3색은 CVD 전체쌍 검증 통과(ΔE 9.2).
   초록(재료)은 배경 대비 3:1 미만이라 모든 노드에 글자 라벨 + 표 보기를 함께 둔다. */

const C = {
  disease: '#2a78d6',
  nutrient: '#eb6834',
  ingredient: '#1baf7a',
  seasoning: '#94a3b8',
  menu: '#07204d',
  forb: '#e34948',
  ink: '#0f172a',
  sub: '#64748b',
  line: '#cbd5e1',
  rec: '#475569',
}
const TYPE_LABEL = { disease: '질환', nutrient: '영양소', ingredient: '재료', menu: '메뉴' }

export const NUTRIENTS = [
  { key: 'na', label: '나트륨' },
  { key: 'protein', label: '단백질' },
  { key: 'energy', label: '에너지' },
  { key: 'ca', label: '칼슘' },
  { key: 'k', label: '칼륨' },
  { key: 'fiber', label: '식이섬유' },
]
export const DISEASES = ['고혈압', '당뇨병', '신장질환', '근감소증', '치매', '연하장애']
const MEAL_CATS = ['국', '주찬', '부찬', '밥', '김치', '간식']

const fmt = (v, d = 1) => (v == null ? '–' : Number(v).toLocaleString('ko-KR', { maximumFractionDigits: d }))

/* ── SVG 툴팁 (viewBox 좌표계 안에서 그려 스케일 문제 없음) ───────── */
function Tip({ x, y, lines, W, H }) {
  if (!lines?.length) return null
  const w = 210
  const h = lines.length * 17 + 14
  const tx = Math.min(Math.max(x + 16, 6), W - w - 6)
  const ty = Math.min(Math.max(y - h / 2, 6), H - h - 6)
  return (
    <g transform={`translate(${tx},${ty})`} pointerEvents="none">
      <rect width={w} height={h} rx={8} fill="#fff" stroke={C.line} />
      {lines.map((t, i) => (
        <text key={i} x={10} y={20 + i * 17} fontSize={i === 0 ? 12.5 : 11.5}
          fontWeight={i === 0 ? 700 : 400} fill={i === 0 ? C.ink : (t.startsWith('⚠') ? C.forb : C.sub)}>
          {t.length > 30 ? t.slice(0, 29) + '…' : t}
        </text>
      ))}
    </g>
  )
}

/* ── ① 메뉴 뜯어보기: 방사형 ─────────────────────────────────── */
export function MenuRadial({ data }) {
  const [hov, setHov] = useState(null)
  const W = 760, H = 500, cx = W / 2, cy = H / 2, R = 172
  const items = (data?.ingredients || []).slice(0, 14)
  const rest = (data?.ingredients || []).length - items.length
  const maxAmt = Math.max(...items.map((i) => i.amount), 0.0001)
  const maxG = Math.max(...items.map((i) => i.edible_g || i.g), 1)

  const pts = items.map((it, k) => {
    const a = (k / items.length) * Math.PI * 2 - Math.PI / 2
    const r = 7 + 19 * Math.sqrt(Math.max(it.amount, 0) / maxAmt)
    return { ...it, x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R, r, a }
  })
  const h = pts.find((p) => p.id === hov)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`${data.menu.title} 재료 구성과 ${data.label} 기여`}>
      {pts.map((p) => (
        <line key={'e' + p.id} x1={cx} y1={cy} x2={p.x} y2={p.y}
          stroke={C.line} strokeWidth={1 + 5 * Math.sqrt((p.edible_g || 0) / maxG)}
          strokeDasharray={p.broth ? '4 4' : undefined}
          opacity={hov && hov !== p.id ? 0.25 : 1} />
      ))}

      <circle cx={cx} cy={cy} r={52} fill={C.menu} />
      <text x={cx} y={cy - 8} textAnchor="middle" fontSize={13} fontWeight={700} fill="#fff">
        {data.menu.title.length > 8 ? data.menu.title.slice(0, 8) + '…' : data.menu.title}
      </text>
      <text x={cx} y={cy + 9} textAnchor="middle" fontSize={11} fill="#c7d2fe">1인분 {fmt(data.menu.serving_g, 0)}g</text>
      <text x={cx} y={cy + 25} textAnchor="middle" fontSize={11} fill="#fff">
        {data.label} {fmt(data.total)}{data.unit}
      </text>

      {pts.map((p) => {
        const dim = hov && hov !== p.id
        const forb = p.forbidden_for?.length > 0
        const cos = Math.cos(p.a), sin = Math.sin(p.a)
        const side = Math.abs(cos) > 0.25
        const anchor = side ? (cos > 0 ? 'start' : 'end') : 'middle'
        const blockH = 14 + (forb ? 13 : 0)           // 첫 줄 기준선 → 마지막 줄 기준선
        const lx = side ? p.x + Math.sign(cos) * (p.r + 8) : p.x
        const ly = side ? p.y + 4 - blockH / 2
          : sin < 0 ? p.y - p.r - 10 - blockH           // 위쪽 노드: 라벨 전체를 원 위로
            : p.y + p.r + 16                            // 아래쪽 노드: 원 아래로
        return (
          <g key={p.id} opacity={dim ? 0.35 : 1}
            onMouseEnter={() => setHov(p.id)} onMouseLeave={() => setHov(null)}
            onFocus={() => setHov(p.id)} onBlur={() => setHov(null)} tabIndex={0} style={{ outline: 'none' }}>
            <circle cx={p.x} cy={p.y} r={Math.max(p.r, 14) + 6} fill="transparent" />
            <circle cx={p.x} cy={p.y} r={p.r}
              fill={p.broth ? '#fff' : (p.seasoning ? C.seasoning : C.ingredient)}
              stroke={forb ? C.forb : (p.sodium_missing || p.broth ? C.sub : '#fff')}
              strokeWidth={forb ? 2.5 : 2}
              strokeDasharray={p.sodium_missing || p.broth ? '3 3' : undefined} />
            <text x={lx} y={ly} textAnchor={anchor} fontSize={12} fontWeight={600} fill={C.ink}>{p.name}</text>
            <text x={lx} y={ly + 14} textAnchor={anchor} fontSize={10.5} fill={C.sub}>
              {fmt(p.g)}g{p.amount > 0 ? ` · ${fmt(p.amount)}${data.unit}` : ''}
            </text>
            {forb && (
              <text x={lx} y={ly + 27} textAnchor={anchor} fontSize={10} fontWeight={700} fill={C.forb}>
                금기 {p.forbidden_for.join('·')}
              </text>
            )}
          </g>
        )
      })}
      {rest > 0 && (
        <text x={W - 10} y={H - 10} textAnchor="end" fontSize={11} fill={C.sub}>외 재료 {rest}개는 표에서 확인</text>
      )}
      {h && (
        <Tip x={h.x} y={h.y} W={W} H={H} lines={[
          h.name,
          `제공 ${fmt(h.g)}g · 먹는 부분 ${fmt(h.edible_g)}g`,
          `100g당 ${data.label} ${fmt(h.per_100g)}${data.unit}`,
          `이 메뉴 기여 ${fmt(h.amount, 2)}${data.unit} (${fmt(h.share)}%)`,
          ...(h.forbidden_why?.length ? [`⚠ 금기 사유: ${h.forbidden_why.join(', ')}`] : []),
          ...(h.seasoning ? ['조미·염장 재료'] : []),
          ...(h.broth ? ['육수 — 영양 계산에서 제외(건져냄)'] : []),
          ...(h.sodium_missing ? ['⚠ 나트륨 자료 없음 — 실제보다 낮게 계산'] : []),
          ...(h.forbidden_for?.length ? [`⚠ 금기: ${h.forbidden_for.join(', ')}`] : []),
        ]} />
      )}
    </svg>
  )
}

function RadialLegend({ unit, label }) {
  const Dot = ({ c, ring, dash }) => (
    <svg width="14" height="14" className="inline-block align-[-2px] mr-1">
      <circle cx="7" cy="7" r="5.5" fill={c} stroke={ring || '#fff'} strokeWidth={ring ? 2 : 1} strokeDasharray={dash} />
    </svg>
  )
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
      <span><Dot c={C.ingredient} />식재료</span>
      <span><Dot c={C.seasoning} />조미·염장 재료</span>
      <span><Dot c={C.ingredient} ring={C.forb} />선택한 질환의 금기</span>
      <span><Dot c="#fff" ring={C.sub} dash="2 2" />육수·나트륨 자료 없음</span>
      <span>원 크기 = {label} 기여({unit}) · 선 굵기 = 먹는 부분 중량</span>
    </div>
  )
}

export function IngredientTable({ data }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs tabular-nums">
        <thead>
          <tr className="text-left text-muted border-b border-navy-100">
            <th className="py-1.5 pr-2 font-medium">재료</th>
            <th className="py-1.5 px-2 font-medium text-right">제공</th>
            <th className="py-1.5 px-2 font-medium text-right">먹는 부분</th>
            <th className="py-1.5 px-2 font-medium text-right">100g당 {data.label}</th>
            <th className="py-1.5 px-2 font-medium text-right">기여</th>
            <th className="py-1.5 px-2 font-medium text-right">비중</th>
            <th className="py-1.5 pl-2 font-medium">비고</th>
          </tr>
        </thead>
        <tbody>
          {data.ingredients.map((i) => (
            <tr key={i.id} className="border-b border-navy-50">
              <td className="py-1.5 pr-2 font-semibold text-navy-900">{i.name}</td>
              <td className="py-1.5 px-2 text-right">{fmt(i.g)}g</td>
              <td className={`py-1.5 px-2 text-right ${i.edible_g !== i.g ? 'text-navy-700 font-semibold' : ''}`}>{fmt(i.edible_g)}g</td>
              <td className="py-1.5 px-2 text-right text-muted">{fmt(i.per_100g)}</td>
              <td className="py-1.5 px-2 text-right">{fmt(i.amount, 2)}{data.unit}</td>
              <td className="py-1.5 px-2 text-right">{fmt(i.share)}%</td>
              <td className="py-1.5 pl-2 text-[11px]">
                {[i.seasoning && '조미', i.broth && '육수(제외)', i.sodium_missing && 'Na 자료 없음']
                  .filter(Boolean).join(' · ')}
                {i.forbidden_for?.length > 0 && (
                  <span className="ml-1 text-rose-700 font-semibold">
                    금기 {i.forbidden_for.join('·')}{i.forbidden_why?.length ? ` (${i.forbidden_why.join('·')})` : ''}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── ② 추천 근거: 질환 → 영양소 → 재료 → 메뉴 ──────────────────── */
export function EvidenceFlow({ data }) {
  const [hov, setHov] = useState(null)
  const COLS = ['disease', 'nutrient', 'ingredient', 'menu']
  const W = 820, BW = 132, BH = 36, ROW = 46, TOP = 44
  const X = { disease: 76, nutrient: 322, ingredient: 520, menu: 740 }   // 질환–영양소 사이를 넓게: 관계 라벨 자리

  const layout = useMemo(() => {
    const by = { disease: [], nutrient: [], ingredient: [], menu: [] }
    for (const n of data.nodes) by[n.type]?.push(n)
    const contains = {}
    for (const e of data.edges) if (e.kind === 'contains' && e.source === 'N:' + data.nutrient) contains[e.target] = e.value
    by.nutrient.sort((a, b) => (b.target ? 1 : 0) - (a.target ? 1 : 0))
    by.ingredient.sort((a, b) => (contains[b.id] || 0) - (contains[a.id] || 0))
    by.disease.sort((a, b) => a.label.localeCompare(b.label))
    const maxN = Math.max(...COLS.map((c) => by[c].length), 1)
    const pos = {}
    for (const c of COLS) {
      const k = by[c].length
      by[c].forEach((n, i) => {
        pos[n.id] = { x: X[c], y: TOP + (maxN - k) * ROW / 2 + i * ROW + BH / 2 }
      })
    }
    return { by, pos, H: TOP + maxN * ROW + 12 }
  }, [data])

  const { by, pos, H } = layout
  const nodeById = Object.fromEntries(data.nodes.map((n) => [n.id, n]))
  const maxVal = Math.max(...data.edges.filter((e) => e.kind === 'contains').map((e) => e.value || 0), 0.0001)
  const touches = (e) => !hov || e.source === hov || e.target === hov

  const path = (a, b) => {
    const x1 = a.x + BW / 2, x2 = b.x - BW / 2
    const dx = (x2 - x1) / 2
    return `M${x1},${a.y} C${x1 + dx},${a.y} ${x2 - dx},${b.y} ${x2},${b.y}`
  }

  const tipFor = (n) => {
    if (!n) return null
    const out = [n.label]
    if (n.sub) out.push(n.sub)
    if (n.type === 'disease') {
      for (const e of data.edges.filter((e) => e.source === n.id)) {
        out.push(`${e.kind === 'rec' ? '권장' : '⚠ 금기'} ${nodeById[e.target]?.label} · 논문 ${e.n_papers}`)
      }
    } else if (n.type === 'nutrient') {
      for (const e of data.edges.filter((e) => e.source === n.id && e.kind === 'contains').slice(0, 5)) {
        out.push(`${nodeById[e.target]?.label} ${e.label}`)
      }
    } else if (n.type === 'ingredient') {
      if (n.seasoning) out.push('조미·염장 재료')
      if (n.sodium_missing) out.push('⚠ 나트륨 자료 없음')
    }
    return out
  }
  const hn = hov && nodeById[hov]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`${data.menu}을 ${data.label} 기준으로 추천한 근거 경로`}>
      {COLS.map((c) => (
        <g key={c}>
          <circle cx={X[c] - 22} cy={18} r={4.5} fill={c === 'menu' ? C.menu : C[c]} />
          <text x={X[c] - 13} y={22} fontSize={12} fontWeight={700} fill={C.sub}>{TYPE_LABEL[c]}</text>
        </g>
      ))}

      {data.edges.map((e, i) => {
        const a = pos[e.source], b = pos[e.target]
        if (!a || !b) return null
        const on = touches(e)
        const isEv = e.kind === 'rec' || e.kind === 'forb'
        const w = e.kind === 'contains' ? 1 + 5 * Math.sqrt((e.value || 0) / maxVal)
          : e.kind === 'in' ? 1.2 : 2
        return (
          <path key={i} d={path(a, b)} fill="none"
            stroke={e.kind === 'forb' ? C.forb : e.kind === 'rec' ? C.rec : C.line}
            strokeWidth={w} strokeDasharray={e.kind === 'forb' ? '6 4' : undefined}
            opacity={on ? (isEv ? 0.95 : 0.9) : 0.12} />
        )
      })}

      {(() => {
        // 관계 라벨은 영양소 상자 바로 앞에, 들어오는 근거 수만큼 위아래로 쌓는다
        const incoming = {}
        for (const e of data.edges) if (e.kind === 'rec' || e.kind === 'forb') { if (!incoming[e.target]) incoming[e.target] = []; incoming[e.target].push(e) }
        return Object.entries(incoming).flatMap(([tid, es]) => es.map((e, k) => {
          const b = pos[tid]
          if (!b || !touches(e)) return null
          const y = b.y + (k - (es.length - 1) / 2) * 17
          const x = b.x - BW / 2 - 40
          const forb = e.kind === 'forb'
          return (
            <g key={tid + k} pointerEvents="none">
              <rect x={x - 3} y={y - 8} width={38} height={16} rx={8} fill="#fff" stroke={forb ? C.forb : C.rec} />
              <text x={x + 16} y={y + 4} textAnchor="middle" fontSize={10.5} fontWeight={700}
                fill={forb ? '#b91c1c' : C.ink}>{forb ? '금기' : '권장'}</text>
            </g>
          )
        }))
      })()}

      {COLS.flatMap((c) => by[c]).map((n) => {
        const p = pos[n.id]
        const isMenu = n.type === 'menu'
        const color = isMenu ? C.menu : (n.type === 'ingredient' && n.seasoning ? C.seasoning : C[n.type])
        const dim = hov && hov !== n.id && !data.edges.some((e) => (e.source === hov && e.target === n.id) || (e.target === hov && e.source === n.id))
        return (
          <g key={n.id} transform={`translate(${p.x - BW / 2},${p.y - BH / 2})`} opacity={dim ? 0.3 : 1}
            onMouseEnter={() => setHov(n.id)} onMouseLeave={() => setHov(null)}
            onFocus={() => setHov(n.id)} onBlur={() => setHov(null)} tabIndex={0} style={{ outline: 'none', cursor: 'default' }}>
            <rect width={BW} height={BH} rx={8}
              fill={isMenu ? C.menu : (n.target ? '#fdf1ec' : '#fff')}
              stroke={isMenu ? C.menu : color} strokeWidth={n.target ? 2 : 1.3} />
            {!isMenu && <rect x={0} y={0} width={5} height={BH} rx={2.5} fill={color} />}
            <text x={isMenu ? BW / 2 : 13} y={n.sub ? 15 : 22} textAnchor={isMenu ? 'middle' : 'start'}
              fontSize={12.5} fontWeight={700} fill={isMenu ? '#fff' : C.ink}>
              {n.label.length > 9 ? n.label.slice(0, 9) + '…' : n.label}
            </text>
            {n.sub && (
              <text x={isMenu ? BW / 2 : 13} y={29} textAnchor={isMenu ? 'middle' : 'start'}
                fontSize={10} fill={isMenu ? '#c7d2fe' : C.sub}>
                {n.sub.length > 19 ? n.sub.slice(0, 19) + '…' : n.sub}
              </text>
            )}
          </g>
        )
      })}
      {hn && <Tip x={pos[hn.id].x + BW / 2 - 10} y={pos[hn.id].y} W={W} H={H} lines={tipFor(hn)} />}
    </svg>
  )
}

export function EvidenceTable({ data }) {
  const byId = Object.fromEntries(data.nodes.map((n) => [n.id, n]))
  const rows = data.edges.filter((e) => e.kind === 'rec' || e.kind === 'forb')
  if (!rows.length) return <p className="text-xs text-muted">선택한 질환과 이어지는 근거가 없습니다.</p>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted border-b border-navy-100">
            <th className="py-1.5 pr-2 font-medium">질환</th>
            <th className="py-1.5 px-2 font-medium">관계</th>
            <th className="py-1.5 px-2 font-medium">영양소</th>
            <th className="py-1.5 px-2 font-medium">이 메뉴의 재료</th>
            <th className="py-1.5 pl-2 font-medium">논문</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e, i) => (
            <tr key={i} className="border-b border-navy-50 align-top">
              <td className="py-1.5 pr-2 font-semibold text-navy-900">{byId[e.source]?.label}</td>
              <td className={`py-1.5 px-2 font-bold ${e.kind === 'forb' ? 'text-rose-700' : 'text-navy-700'}`}>{e.kind === 'forb' ? '금기' : '권장'}</td>
              <td className="py-1.5 px-2">{byId[e.target]?.label}</td>
              <td className="py-1.5 px-2">{e.ingredients.join(', ')}</td>
              <td className="py-1.5 pl-2 text-[11px] text-muted">
                <b className="text-navy-900 tabular-nums">{e.n_papers}편</b>
                {e.papers.slice(0, 2).map((t, j) => <span key={j} className="block leading-5">· {t}</span>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── 메뉴 상세 (탭·패널 공용) ─────────────────────────────────── */
function Chip({ on, onClick, children, tone = 'navy' }) {
  const onCls = tone === 'rose' ? 'bg-rose-600 text-white' : 'bg-navy-900 text-white'
  return (
    <button type="button" onClick={onClick}
      className={`badge transition ${on ? onCls : 'bg-navy-50 text-navy-700 hover:bg-navy-100'}`}>{children}</button>
  )
}

export function MenuDetail({ name, nutrient: n0 = 'na', diseases: d0 = [], initialView = 'radial' }) {
  const [nutrient, setNutrient] = useState(n0)
  const [diseases, setDiseases] = useState(d0)
  const [view, setView] = useState(initialView)
  const [table, setTable] = useState(false)
  const [mg, setMg] = useState(null)
  const [eg, setEg] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => { setNutrient(n0) }, [n0])
  useEffect(() => { setDiseases(d0) }, [d0.join(',')])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!name) return
    let live = true
    setBusy(true); setErr('')
    const params = { name, nutrient, diseases: diseases.join(',') }
    Promise.all([
      api.get('/care/facility/graph/menu', { params }),
      api.get('/care/facility/graph/evidence', { params }),
    ])
      .then(([a, b]) => { if (live) { setMg(a.data); setEg(b.data) } })
      .catch((e) => live && setErr(errMsg(e)))
      .finally(() => live && setBusy(false))
    return () => { live = false }
  }, [name, nutrient, diseases.join(',')])  // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (d) => setDiseases((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]))

  if (!name) return <p className="text-sm text-muted py-10 text-center">왼쪽에서 메뉴를 고르세요.</p>
  if (err) return <p className="text-sm text-red-700 py-4">{err}</p>
  if (!mg) return <p className="text-sm text-muted py-10 text-center">불러오는 중…</p>

  const nut = mg.nutrition
  return (
    <div className={`space-y-4 ${busy ? 'opacity-70' : ''}`}>
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-extrabold text-navy-900">{mg.menu.title}</h3>
          {mg.menu.meal_cat && <span className="badge bg-navy-50 text-navy-700">{mg.menu.meal_cat}</span>}
          <span className="text-xs text-muted tabular-nums">1인분 {fmt(mg.menu.serving_g, 0)}g</span>
        </div>
        <div className="mt-2 grid grid-cols-3 sm:grid-cols-5 gap-2 text-center">
          {[['에너지', nut.energy_kcal, 'kcal', 0], ['단백질', nut.protein_g, 'g', 1], ['나트륨', nut.sodium_mg, 'mg', 0],
            ['칼슘', nut.calcium_mg, 'mg', 0], ['식이섬유', nut.fiber_g, 'g', 1]].map(([l, v, u, d]) => (
            <div key={l} className="rounded-xl bg-navy-50/70 px-2 py-2">
              <p className="text-[10.5px] text-muted">{l}</p>
              <p className="text-sm font-extrabold tabular-nums text-navy-900">{fmt(v, d)}<span className="ml-0.5 text-[10px] font-normal text-muted">{u}</span></p>
            </div>
          ))}
        </div>
        {(mg.sodium_underestimated || mg.broth_missing) && (
          <div className="mt-2 space-y-0.5 text-[11px] text-rose-700">
            {mg.sodium_underestimated && <p>※ 나트륨 과소 추정 — {mg.sodium_underestimated.join(', ')}의 나트륨 자료가 없습니다.</p>}
            {mg.broth_missing && <p>※ 국물(육수)이 재료로 등록돼 있지 않아 중량이 건더기뿐입니다.</p>}
          </div>
        )}
      </div>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="w-12 text-[11px] text-muted">영양소</span>
          {NUTRIENTS.map((x) => <Chip key={x.key} on={nutrient === x.key} onClick={() => setNutrient(x.key)}>{x.label}</Chip>)}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="w-12 text-[11px] text-muted">질환</span>
          {DISEASES.map((d) => <Chip key={d} tone="rose" on={diseases.includes(d)} onClick={() => toggle(d)}>{d}</Chip>)}
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-navy-100">
        {[['radial', '재료 구성'], ['evidence', '추천 근거']].map(([k, l]) => (
          <button key={k} type="button" onClick={() => setView(k)}
            className={`px-3 py-2 text-sm font-bold border-b-2 -mb-px ${view === k ? 'border-navy-900 text-navy-900' : 'border-transparent text-muted hover:text-navy-700'}`}>{l}</button>
        ))}
        <button type="button" onClick={() => setTable((t) => !t)}
          className="ml-auto text-[11px] text-navy-600 underline">{table ? '그래프로 보기' : '표로 보기'}</button>
      </div>

      {view === 'radial' && (
        table ? <IngredientTable data={mg} /> : (
          <>
            <MenuRadial data={mg} />
            <RadialLegend unit={mg.unit} label={mg.label} />
          </>
        )
      )}

      {view === 'evidence' && eg && (
        <>
          {table ? <EvidenceTable data={eg} /> : (
            <>
              <EvidenceFlow data={eg} />
              <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                <span><svg width="22" height="8" className="inline-block mr-1"><line x1="0" y1="4" x2="22" y2="4" stroke={C.rec} strokeWidth="2" /></svg>권장 근거</span>
                <span><svg width="22" height="8" className="inline-block mr-1"><line x1="0" y1="4" x2="22" y2="4" stroke={C.forb} strokeWidth="2" strokeDasharray="6 4" /></svg>금기 근거</span>
                <span>영양소→재료 선 굵기 = 이 메뉴에서의 실제 기여량</span>
              </div>
            </>
          )}
          <p className="text-[11px] text-muted">
            질환–영양소 근거는 논문에서 추출한 관계입니다. 영양성분표로 확인할 수 없는 근거
            {eg.excluded_unverifiable > 0 ? ` ${eg.excluded_unverifiable}건` : ''}(예: 소금 → 마그네슘 → 고혈압)은 그리지 않았습니다.
            조미·염장 재료는 권장 급원으로 잇지 않습니다.
          </p>
        </>
      )}
    </div>
  )
}

/* ── 식품 DB 탭 ─────────────────────────────────────────────── */
export function MenuExplorer({ diseases = [] }) {
  const [q, setQ] = useState('')
  const [cat, setCat] = useState('')
  const [list, setList] = useState([])
  const [sel, setSel] = useState('')
  const [err, setErr] = useState('')

  useEffect(() => {
    const t = setTimeout(() => {
      api.get('/care/facility/graph/search', { params: { q, meal_cat: cat || undefined, limit: 60 } })
        .then((r) => { setList(r.data.items || []); setErr('') })
        .catch((e) => setErr(errMsg(e)))
    }, 250)
    return () => clearTimeout(t)
  }, [q, cat])

  return (
    <div className="grid md:grid-cols-[260px_1fr] gap-5">
      <div className="space-y-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="메뉴 이름 (예: 미역국)"
          className="w-full rounded-xl border border-navy-100 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-navy-200" />
        <div className="flex flex-wrap gap-1">
          <Chip on={!cat} onClick={() => setCat('')}>전체</Chip>
          {MEAL_CATS.map((c) => <Chip key={c} on={cat === c} onClick={() => setCat(c)}>{c}</Chip>)}
        </div>
        {err && <p className="text-xs text-red-700">{err}</p>}
        <ul className="max-h-[560px] overflow-y-auto divide-y divide-navy-50 rounded-xl ring-1 ring-navy-100 bg-white">
          {list.map((m) => (
            <li key={m.id}>
              <button type="button" onClick={() => setSel(m.title)}
                className={`w-full text-left px-3 py-2 ${sel === m.title ? 'bg-navy-50' : 'hover:bg-navy-50/50'}`}>
                <span className="flex items-center gap-1.5">
                  <span className="text-sm font-semibold text-navy-900 truncate">{m.title}</span>
                  <span className="ml-auto shrink-0 text-[10px] text-muted">{m.meal_cat}</span>
                </span>
                <span className="block text-[11px] tabular-nums text-muted">
                  {fmt(m.serving_g, 0)}g · {m.energy_kcal}kcal · 단백질 {m.protein_g}g · 나트륨 {m.sodium_mg}mg{m.sodium_underestimated ? '↑' : ''}
                </span>
              </button>
            </li>
          ))}
          {!list.length && <li className="px-3 py-6 text-center text-xs text-muted">검색 결과가 없습니다.</li>}
        </ul>
        <p className="text-[10.5px] text-muted">나트륨 뒤 ↑ 표시는 자료가 빠져 실제보다 낮게 계산된 메뉴입니다.</p>
      </div>
      <div className="min-w-0">
        <MenuDetail key={sel} name={sel} diseases={diseases} />
      </div>
    </div>
  )
}

/* ── 개선안에서 여는 옆 패널 ───────────────────────────────────── */
export function MenuDrawer({ open, name, nutrient, diseases = [], onClose }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 no-print">
      <div className="absolute inset-0 bg-navy-950/30" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full max-w-[820px] overflow-y-auto bg-white shadow-2xl p-6">
        <div className="flex items-center justify-between mb-3">
          <p className="text-xs font-bold text-navy-500">왜 이 메뉴인가</p>
          <button type="button" onClick={onClose} className="btn-secondary text-sm">닫기</button>
        </div>
        <MenuDetail key={name + nutrient} name={name} nutrient={nutrient} diseases={diseases} initialView="evidence" />
      </aside>
    </div>
  )
}

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
  product: '#7c3aed',
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
const won = (v) => (v == null ? '–' : `${Number(v).toLocaleString('ko-KR')}원`)

export function MenuRadial({ data }) {
  const [hov, setHov] = useState(null)
  const [sel, setSel] = useState(null)      // 누른 재료 → 매핑된 공급사 상품 펼치기
  const [prod, setProd] = useState({})      // 재료 id → 응답 | 'loading' | {error}
  const W = 760, H = 500, cx = W / 2, cy = H / 2, R = 172
  const PAD = 70                            // 바깥쪽 상품 노드 자리
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

  const pick = (id) => {
    setSel((s) => (s === id ? null : id))
    if (!prod[id] || prod[id].error) {
      setProd((m) => ({ ...m, [id]: 'loading' }))
      api.get('/care/facility/graph/products', { params: { recipe_id: id }, timeout: 30000 })
        .then((r) => setProd((m) => ({ ...m, [id]: r.data })))
        .catch((e) => setProd((m) => ({ ...m, [id]: { error: errMsg(e) } })))
    }
  }
  const sp = pts.find((p) => p.id === sel)
  const pd = sel ? prod[sel] : null
  const list = pd && pd.products ? pd.products : []
  // 상품 카드: 재료 바깥쪽에 세로로 나란히 (위·아래 재료는 오른쪽) — 선은 재료 원 가장자리에서 카드 가장자리로
  const CW = 196, CH = 42, CG = 10
  const sats = sp ? (() => {
    const right = Math.cos(sp.a) >= -0.25
    const x0 = right ? Math.min(sp.x + sp.r + 44, W + PAD - CW - 4) : Math.max(sp.x - sp.r - 44 - CW, -PAD + 4)
    const arr = list.slice(0, 3)
    const top0 = sp.y - (arr.length * CH + (arr.length - 1) * CG) / 2
    return arr.map((q, i) => {
      const y = Math.min(Math.max(top0 + i * (CH + CG), -PAD + 4), H + PAD - CH - 4)
      return { ...q, right, x: x0, y, ax: right ? x0 : x0 + CW, ay: y + CH / 2 }
    })
  })() : []

  return (
    <div>
    <svg viewBox={`${-PAD} ${-PAD} ${W + PAD * 2} ${H + PAD * 2}`} className="w-full h-auto" role="img"
      aria-label={`${data.menu.title} 재료 구성과 ${data.label} 기여`}>
      {pts.map((p) => (
        <line key={'e' + p.id} x1={cx} y1={cy} x2={p.x} y2={p.y}
          stroke={C.line} strokeWidth={1 + 5 * Math.sqrt((p.edible_g || 0) / maxG)}
          strokeDasharray={p.broth ? '4 4' : undefined}
          opacity={(hov && hov !== p.id) || (sel && sel !== p.id && !hov) ? 0.25 : 1} />
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
        const side = Math.abs(cos) > 0.25 && sel !== p.id      // 선택된 재료는 라벨을 원 아래로 (카드 자리 비움)
        const anchor = side ? (cos > 0 ? 'start' : 'end') : 'middle'
        const blockH = 14 + (forb ? 13 : 0)           // 첫 줄 기준선 → 마지막 줄 기준선
        const lx = side ? p.x + Math.sign(cos) * (p.r + 8) : p.x
        const ly = side ? p.y + 4 - blockH / 2
          : sin < 0 && sel !== p.id ? p.y - p.r - 10 - blockH   // 위쪽 노드: 라벨 전체를 원 위로
            : p.y + p.r + 16                            // 아래쪽 노드: 원 아래로
        return (
          <g key={p.id} opacity={dim || (sel && sel !== p.id && !hov) ? 0.35 : 1} className="cursor-pointer"
            onMouseEnter={() => setHov(p.id)} onMouseLeave={() => setHov(null)} onClick={() => pick(p.id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(p.id) } }}
            onFocus={() => setHov(p.id)} onBlur={() => setHov(null)} tabIndex={0} role="button"
            aria-label={`${p.name} 공급사 상품 보기`} style={{ outline: 'none' }}>
            {sel === p.id && <circle cx={p.x} cy={p.y} r={p.r + 5} fill="none" stroke={C.product} strokeWidth={2} />}
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
      {sats.map((q, i) => {
        const nm = q.item_nm || q.item_cd
        const sx = sp.x + (q.right ? 1 : -1) * (sp.r + 4)
        const mx = (sx + q.ax) / 2
        const sub = [q.supplier_label, q.spec].filter(Boolean).join(' · ')
        return (
          <g key={q.supplier + q.item_cd}>
            <path d={`M${sx},${sp.y} C${mx},${sp.y} ${mx},${q.ay} ${q.ax},${q.ay}`} fill="none"
              stroke={C.product} strokeWidth={q.selected ? 2 : 1.25} opacity={q.selected ? 0.8 : 0.45} />
            <g transform={`translate(${q.x},${q.y})`}>
              <title>{`${q.supplier_label} · ${nm}${q.spec ? ` (${q.spec})` : ''}\nkg당 ${won(q.price_per_kg)}${q.selected ? ' · 오늘 최저가' : ''}${q.on_sale === false ? ' · 오늘 판매 안 함' : ''}`}</title>
              <rect width={CW} height={CH} rx={10} fill={q.selected ? '#f5f3ff' : '#fff'}
                stroke={q.selected ? C.product : '#ddd6fe'} strokeWidth={q.selected ? 1.5 : 1} />
              <rect x={0} y={8} width={3} height={CH - 16} rx={1.5} fill={q.selected ? C.product : '#c4b5fd'} />
              <text x={12} y={17} fontSize={11.5} fontWeight={700} fill={C.ink}>
                {(() => { const k = q.selected || q.on_sale === false ? 12 : 16; return nm.length > k ? nm.slice(0, k - 1) + '…' : nm })()}</text>
              <text x={12} y={32} fontSize={10.5} fill={C.sub}>
                <tspan fontWeight={700} fill={q.selected ? C.product : C.ink}>{won(q.price_per_kg)}</tspan>
                <tspan>/kg · {sub.length > 18 ? sub.slice(0, 17) + '…' : sub}</tspan>
              </text>
              {q.selected && (
                <g transform={`translate(${CW - 34},6)`}>
                  <rect width={28} height={14} rx={7} fill={C.product} />
                  <text x={14} y={10.5} textAnchor="middle" fontSize={9} fontWeight={700} fill="#fff">최저</text>
                </g>
              )}
              {q.on_sale === false && !q.selected && (
                <g transform={`translate(${CW - 54},6)`}>
                  <rect width={48} height={14} rx={7} fill="#f1f5f9" />
                  <text x={24} y={10.5} textAnchor="middle" fontSize={9} fontWeight={600} fill={C.sub}>판매 안 함</text>
                </g>
              )}
            </g>
          </g>
        )
      })}
      {sp && pd === 'loading' && (
        <text x={sp.x + (Math.cos(sp.a) >= -0.25 ? sp.r + 44 : -sp.r - 44)} y={sp.y + 4}
          textAnchor={Math.cos(sp.a) >= -0.25 ? 'start' : 'end'} fontSize={11} fill={C.sub}>공급사 상품 불러오는 중…</text>
      )}
      {rest > 0 && (
        <text x={W + PAD - 10} y={H + PAD - 10} textAnchor="end" fontSize={11} fill={C.sub}>외 재료 {rest}개는 표에서 확인</text>
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
          sel === h.id ? '다시 누르면 공급사 상품 닫기' : '누르면 공급사 상품 보기',
        ]} />
      )}
    </svg>
    <ProductPanel ing={sp} pd={pd} onClose={() => setSel(null)} />
    {!sel && <p className="mt-1 text-[11px] text-muted">재료 노드를 누르면 Neo4j에 매핑된 공급사 상품(상품명·kg당 가격·공급사)이 펼쳐집니다.</p>}
    </div>
  )
}

// [2026-11-27] 재료 → 공급사 상품 목록 (오늘 최저가로 뽑힌 상품부터)
function ProductPanel({ ing, pd, onClose }) {
  if (!ing) return null
  const box = (child) => (
    <div className="mt-2 rounded-xl bg-white px-4 py-3 ring-1 ring-violet-200">
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: C.product }} />
        <p className="text-sm font-bold text-navy-900">{ing.name} <span className="font-normal text-muted">— 매핑된 공급사 상품</span></p>
        <button type="button" onClick={onClose} className="ml-auto text-xs text-muted hover:text-navy-900">닫기 ✕</button>
      </div>
      {child}
    </div>
  )
  if (!pd || pd === 'loading') return box(<p className="text-xs text-muted">Neo4j에서 불러오는 중…</p>)
  if (pd.error) return box(<p className="text-xs text-red-700">{pd.error}</p>)
  if (!pd.available) return box(<p className="text-xs text-amber-700">{pd.reason}</p>)
  if (!pd.products?.length) {
    return box(<p className="text-xs text-muted">{pd.price_status === 'not_product'
      ? '육수·국물 같은 조리 중간물이라 공급사 상품을 연결하지 않습니다.'
      : '아직 승인된 공급사 상품이 없습니다. (식자재 매핑 검수에서 확인)'}</p>)
  }
  const sup = { hgreenfood: '현대그린푸드', sajo: '사조푸디스트' }
  return box(<>
    <p className="mb-2 text-xs text-ink">
      오늘 최저 <b className="text-navy-900">{won(pd.price_per_kg)}/kg</b>
      {pd.price_supplier && <span className="text-muted"> · {sup[pd.price_supplier] || pd.price_supplier}</span>}
      {pd.price_date && <span className="text-muted"> · {pd.price_date} 기준</span>}
      <span className="text-muted"> · 승인된 상품 {pd.n_products}개{pd.n_products > pd.products.length ? ` 중 ${pd.products.length}개` : ''}</span>
    </p>
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="text-muted"><tr className="border-b border-navy-50">
          <th className="py-1 text-left font-semibold">공급사</th><th className="text-left font-semibold">상품명</th>
          <th className="text-left font-semibold">규격</th><th className="text-right font-semibold">kg당 가격</th><th className="pl-3 text-left font-semibold"></th>
        </tr></thead>
        <tbody>
          {pd.products.map((q) => (
            <tr key={q.supplier + q.item_cd} className="border-b border-navy-50 last:border-0">
              <td className="py-1.5 pr-2 whitespace-nowrap">{q.supplier_label}</td>
              <td className="pr-2 text-navy-900">{q.item_nm || q.item_cd}</td>
              <td className="pr-2 text-muted">{q.spec}{q.unit ? ` · ${q.unit}` : ''}</td>
              <td className="text-right tabular-nums font-semibold text-navy-900">{won(q.price_per_kg)}</td>
              <td className="pl-3 whitespace-nowrap">
                {q.selected && <span className="badge bg-violet-50 text-violet-700">오늘 최저가</span>}
                {!q.selected && q.selected_in_supplier && <span className="badge bg-navy-50 text-navy-700">공급사 최저</span>}
                {q.on_sale === false && <span className="badge bg-slate-100 text-slate-500">오늘 판매 안 함</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <p className="mt-1.5 text-[10.5px] text-muted">kg당 가격은 세금 포함 단가를 규격 중량으로 나눈 값이에요. 매핑은 식자재 매핑 파이프라인이 매일 갱신합니다.</p>
  </>)
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

/* ── 식품 DB 첫 화면: 지식그래프 한눈에 ─────────────────────────────
   위에서 아래로: 숫자 → 끼니 구분 → 많이 쓰는 식재료 분류(막대) → 질환별 권장·주의 재료(카드).
   막대는 한 가지 색(크기만 표현) · 값은 막대 옆에 글자로 · 권장/주의는 색과 함께 ✓/⚠ 기호와 글자. */
function OvStat({ label, value, sub }) {
  return (
    <div className="rounded-xl bg-navy-50/70 px-4 py-3">
      <p className="text-[11px] font-semibold text-muted">{label}</p>
      <p className="mt-0.5 text-xl font-bold text-navy-900 tabular-nums">{value}</p>
      {sub && <p className="text-[11px] text-muted">{sub}</p>}
    </div>
  )
}

export function GraphOverview({ onPickMenu, onPickCat }) {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)      // 펼친 식재료 분류
  const [showAll, setShowAll] = useState(false)

  useEffect(() => {
    api.get('/care/facility/graph/overview', { timeout: 60000 })
      .then((r) => { setD(r.data); setErr('') }).catch((e) => setErr(errMsg(e)))
  }, [])

  if (err) return <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{err}</p>
  if (!d) return <p className="py-16 text-center text-sm text-muted">식품 지식그래프를 불러오는 중…</p>

  const st = d.stats || {}
  const cats = d.categories.filter((c) => c.name !== '기타')
  const shown = showAll ? cats : cats.slice(0, 8)
  const maxCat = Math.max(1, ...cats.map((c) => c.n_menus))
  const maxMeal = Math.max(1, ...d.meal_cats.map((m) => m.n))
  const diseases = DISEASES.filter((x) => d.disease_top?.[x])

  return (
    <div className="space-y-6">
      {/* 머리 */}
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-base font-bold text-navy-900">식품 지식그래프 한눈에</h3>
        <span className={`badge ${d.source === 'neo4j' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'}`}>
          {d.source === 'neo4j' ? '● Neo4j 연결됨' : '● 스냅샷 (Neo4j 연결 안 됨)'}
        </span>
        <span className="ml-auto text-[11px] text-muted">왼쪽에서 메뉴를 고르면 재료·영양 상세가 열립니다</span>
      </div>

      {/* ① 숫자 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <OvStat label="요리" value={fmt(st.foods, 0)} sub="레시피 DB 메뉴" />
        <OvStat label="식재료" value={fmt(st.ingredients, 0)} sub="식약처 영양성분 연결" />
        <OvStat label="질환 근거" value={fmt(st.evidence, 0)} sub={`질환 ${st.diseases}개 · 권장·주의 관계`} />
        <OvStat label="근거 논문" value={fmt(st.papers, 0)} sub="편" />
      </div>

      {/* ② 끼니 구분 */}
      <section>
        <p className="mb-2 text-xs font-bold text-navy-800">끼니 구분 <span className="font-normal text-muted">· 누르면 왼쪽 목록이 걸러집니다</span></p>
        <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
          {d.meal_cats.map((m) => (
            <button key={m.name} type="button" onClick={() => onPickCat?.(m.name)}
              className="rounded-xl bg-white px-3 py-2 text-left ring-1 ring-navy-100 hover:ring-navy-300 hover:bg-navy-50/50 transition">
              <span className="block text-sm font-semibold text-navy-900">{m.name}</span>
              <span className="block text-[11px] tabular-nums text-muted">{fmt(m.n, 0)}개</span>
              <span className="mt-1.5 block h-1 rounded-full bg-navy-50">
                <span className="block h-1 rounded-full bg-navy-500" style={{ width: `${(m.n / maxMeal) * 100}%` }} />
              </span>
            </button>
          ))}
        </div>
      </section>

      <div className="grid xl:grid-cols-2 gap-6">
        {/* ③ 많이 쓰는 식재료 분류 */}
        <section>
          <p className="mb-2 text-xs font-bold text-navy-800">많이 쓰는 식재료 분류 <span className="font-normal text-muted">· 그 분류 재료가 든 요리 수 · 누르면 재료</span></p>
          <ul className="space-y-1">
            {shown.map((c) => (
              <li key={c.name}>
                <button type="button" onClick={() => setOpen(open === c.name ? null : c.name)}
                  title={`${c.name} · 재료 ${fmt(c.n_ingredients, 0)}개 · 요리 ${fmt(c.n_menus, 0)}개`}
                  className={`w-full grid grid-cols-[7.5rem_1fr_4.5rem] items-center gap-2 rounded-lg px-2 py-1.5 text-left transition ${open === c.name ? 'bg-navy-50' : 'hover:bg-navy-50/60'}`}>
                  <span className="truncate text-xs font-semibold text-navy-900">{c.name}</span>
                  <span className="h-2 rounded-full bg-navy-50">
                    <span className="block h-2 rounded-full bg-navy-500" style={{ width: `${(c.n_menus / maxCat) * 100}%` }} />
                  </span>
                  <span className="text-right text-[11px] tabular-nums text-muted">{fmt(c.n_menus, 0)}</span>
                </button>
                {open === c.name && (
                  <div className="mx-2 mb-2 mt-1 rounded-lg bg-white px-3 py-2 ring-1 ring-navy-100">
                    <p className="mb-1.5 text-[11px] text-muted">재료 {fmt(c.n_ingredients, 0)}개 중 많이 쓰는 순 · 메뉴를 누르면 상세가 열립니다</p>
                    <div className="space-y-1.5">
                      {c.top.slice(0, 6).map((t) => (
                        <div key={t.ingredient} className="text-xs">
                          <span className="font-semibold text-navy-900">{t.ingredient}</span>
                          <span className="ml-1 text-[11px] text-muted">요리 {fmt(t.n_menus, 0)}</span>
                          <span className="ml-2">
                            {t.menus.slice(0, 3).map((mn) => (
                              <button key={mn} type="button" onClick={() => onPickMenu?.(mn)}
                                className="mr-1 mb-0.5 rounded-md bg-navy-50 px-1.5 py-0.5 text-[11px] text-navy-700 hover:bg-navy-100">{mn}</button>
                            ))}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {cats.length > 8 && (
            <button type="button" onClick={() => setShowAll(!showAll)} className="mt-1 px-2 text-[11px] font-semibold text-navy-700 hover:underline">
              {showAll ? '접기' : `분류 ${cats.length - 8}개 더 보기`}
            </button>
          )}
        </section>

        {/* ④ 질환별 근거 재료 */}
        <section>
          <p className="mb-2 text-xs font-bold text-navy-800">질환별 근거 재료 <span className="font-normal text-muted">· 논문 근거로 연결된 권장·주의 재료</span></p>
          <div className="grid sm:grid-cols-2 gap-2">
            {diseases.map((name) => {
              const v = d.disease_top[name]
              return (
                <div key={name} className="rounded-xl bg-white px-3 py-2.5 ring-1 ring-navy-100">
                  <p className="text-sm font-bold text-navy-900">{name}</p>
                  <p className="mt-1.5 text-[11px] font-semibold text-emerald-700">✓ 권장 {v.recommended.n}개</p>
                  <p className="text-[11.5px] leading-relaxed text-ink">{v.recommended.top.slice(0, 4).map((t) => t.ingredient).join(' · ') || '–'}</p>
                  <p className="mt-1 text-[11px] font-semibold text-red-700">⚠ 주의 {v.forbidden.n}개</p>
                  <p className="text-[11.5px] leading-relaxed text-ink">{v.forbidden.top.slice(0, 4).map((t) => t.ingredient).join(' · ') || '–'}</p>
                </div>
              )
            })}
          </div>
          <p className="mt-2 text-[10.5px] text-muted">권장은 근거가 많은 재료, 주의는 요리에 많이 쓰이는 재료부터. 같은 질환에서 권장·주의가 함께 걸린 재료(예: 단백질 권장·콜레스테롤 주의)와 조미 재료의 권장은 뺐습니다.</p>
        </section>
      </div>
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
        {sel ? (<>
          <button type="button" onClick={() => setSel('')} className="mb-2 text-xs font-semibold text-navy-700 hover:underline">← 전체 그래프</button>
          <MenuDetail key={sel} name={sel} diseases={diseases} />
        </>) : (
          <GraphOverview onPickMenu={setSel} onPickCat={setCat} />
        )}
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

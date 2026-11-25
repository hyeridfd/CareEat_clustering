import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout, { Empty } from '../../components/care/CareLayout'
import { errMsg } from '../../components/care/CareUI'

// 공급사 표시: 색 점 + 이름 (색만으로 구분하지 않음)
const SUP = {
  hgreenfood: { label: '현대그린푸드', short: '현대', dot: 'bg-emerald-500', soft: 'bg-emerald-50 text-emerald-800 border-emerald-200' },
  sajo: { label: '사조푸디스트', short: '사조', dot: 'bg-amber-500', soft: 'bg-amber-50 text-amber-800 border-amber-200' },
}
const QUICK = ['두부', '계란', '닭가슴살', '고등어', '애호박', '단호박', '연어', '다짐육', '순두부', '바나나']
const TAGS = [
  { id: 'soft', label: '부드러운 식감', hint: '다짐·무스·퓨레·연육·고령친화' },
  { id: 'lowsalt', label: '저염·저당', hint: '저염·저당·무염·저나트륨' },
]
const STORAGE = ['냉장', '냉동', '실온']
const STORAGE_STYLE = { 냉장: 'text-sky-700 bg-sky-50', 냉동: 'text-indigo-700 bg-indigo-50', 실온: 'text-stone-600 bg-stone-100' }
const PAGE = 40
const WD = ['일', '월', '화', '수', '목', '금', '토']

const won = (v) => (v == null ? '—' : `${Math.round(v).toLocaleString('ko-KR')}원`)
function fmtDay(d) {
  if (!d) return ''
  const [y, m, day] = d.slice(0, 10).split('-')
  return `${+m}.${+day}(${WD[new Date(+y, +m - 1, +day).getDay()]})`
}
function fmtTime(iso) {
  if (!iso) return ''
  const t = new Date(iso)
  return Number.isNaN(t.getTime()) ? '' : `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
}
// '(C)양배추(상품,실온,겉잎제거,국산)' → 이름 '양배추' + 속성 '상품 · 겉잎제거' (보관·원산지는 따로 배지로 보여주므로 뺌)
function splitName(nm = '') {
  const prefix = (nm.match(/^(\([^)]*\)|\[[^\]]*\])/) || [''])[0]
  const rest = nm.slice(prefix.length)
  const i = rest.indexOf('(')
  if (i <= 0) return { name: rest || nm, attrs: '' }
  const name = rest.slice(0, i)
  const inner = rest.slice(i + 1).replace(/\)$/, '')
  const attrs = inner.split(',').map((s) => s.trim())
    .filter((s) => s && !['냉장', '냉동', '실온', '상온', '국산', '수입', '상품'].includes(s)).join(' · ')
  return { name, attrs }
}

function SupBadge({ sup, short }) {
  const s = SUP[sup]
  if (!s) return null
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-navy-900 whitespace-nowrap">
      <span className={`w-2 h-2 rounded-full ${s.dot}`} />{short ? s.short : s.label}
    </span>
  )
}

function Change({ c, compact }) {
  if (!c || !c.pct) return null
  const up = c.pct > 0
  return (
    <span className={`inline-flex items-center gap-0.5 text-[11px] font-semibold tabular-nums ${up ? 'text-red-600' : 'text-navy-600'}`}
      title={`${fmtDay(c.on)} ${won(c.prev)} → ${won(c.now)}`}>
      {up ? '▲' : '▼'}{Math.abs(c.pct)}%{!compact && <span className="font-normal text-muted ml-1">{fmtDay(c.on)}</span>}
    </span>
  )
}

function Seg({ value, onChange, options }) {
  return (
    <div className="inline-flex rounded-xl bg-navy-50 p-0.5">
      {options.map(([v, label]) => (
        <button key={label} onClick={() => onChange(v)}
          className={`px-3 py-1.5 rounded-[10px] text-xs font-semibold transition whitespace-nowrap ${
            value === v ? 'bg-white text-navy-900 shadow-sm' : 'text-muted hover:text-navy-700'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}

export default function IngredientsPage() {
  const [params, setParams] = useSearchParams()
  const [input, setInput] = useState(params.get('q') || '')
  const q = params.get('q') || ''
  const [tag, setTag] = useState(params.get('tag') || '')
  const [supplier, setSupplier] = useState('')
  const [storage, setStorage] = useState('')
  const [origin, setOrigin] = useState('')
  const [category, setCategory] = useState('')
  const [sort, setSort] = useState('relevance')
  const [vat, setVat] = useState(true)
  const [summary, setSummary] = useState(null)
  const [res, setRes] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(null)        // 상세 패널에 띄운 품목
  const [showMovers, setShowMovers] = useState(false)
  const reqId = useRef(0)
  const inputRef = useRef(null)

  useEffect(() => {
    api.get('/prices/summary').then((r) => setSummary(r.data)).catch((e) => setErr(errMsg(e)))
  }, [])

  // 입력은 0.3초 멈추면 검색 (주소에 남겨 새로고침·공유해도 그대로)
  useEffect(() => {
    const t = setTimeout(() => {
      if (input.trim() === q) return
      const next = new URLSearchParams(params)
      input.trim() ? next.set('q', input.trim()) : next.delete('q')
      setParams(next, { replace: true })
    }, 300)
    return () => clearTimeout(t)
  }, [input]) // eslint-disable-line react-hooks/exhaustive-deps

  const filters = { q, tag, supplier, storage, origin, category, sort, vat }
  const fetchPage = (offset) => {
    const id = ++reqId.current
    const p = { q, sort, vat, limit: PAGE, offset }
    if (tag) p.tag = tag
    if (supplier) p.supplier = supplier
    if (storage) p.storage = storage
    if (origin) p.origin = origin
    if (category) p.category = category
    setLoading(true); setErr('')
    return api.get('/prices/search', { params: p })
      .then((r) => {
        if (id !== reqId.current) return
        setRes((prev) => (offset && prev ? { ...r.data, items: [...prev.items, ...r.data.items] } : r.data))
      })
      .catch((e) => id === reqId.current && setErr(errMsg(e)))
      .finally(() => id === reqId.current && setLoading(false))
  }
  useEffect(() => {
    if (!q && !tag && !category) { setRes(null); return }
    fetchPage(0)
  }, [JSON.stringify(filters)]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (word) => { setInput(word); setTag(''); inputRef.current?.focus() }
  const pk = vat ? 'per_kg_tax' : 'per_kg'
  const pp = vat ? 'unit_price_tax' : 'unit_price'
  const searching = !!(q || tag || category)
  const anyFilter = supplier || storage || origin || category

  const updated = summary?.suppliers?.map((s) => s.updated_at).filter(Boolean).sort().pop()

  return (
    <CareLayout
      title="식자재"
      subtitle="현대그린푸드·사조푸디스트 계약 단가를 매일 아침 반영합니다. 규격을 kg당 가격으로 환산해 비교해 보세요."
      actions={updated && (
        <span className="text-xs text-muted">최근 반영 <b className="text-navy-900 font-semibold">{fmtDay(updated)} {fmtTime(updated)}</b></span>
      )}
    >
      {err && <p className="mb-4 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}

      {/* 공급사 현황 + 오늘 단가 변동 */}
      {summary && (
        <section className="grid gap-3 md:grid-cols-3 mb-5">
          {summary.suppliers.map((s) => (
            <button key={s.supplier} onClick={() => setSupplier(supplier === s.supplier ? '' : s.supplier)}
              className={`surface px-5 py-4 text-left transition hover:border-navy-200 ${supplier === s.supplier ? 'ring-2 ring-navy-600 border-transparent' : ''}`}>
              <SupBadge sup={s.supplier} />
              <p className="mt-2 text-2xl font-extrabold tracking-tight text-navy-900 tabular-nums">
                {s.items.toLocaleString('ko-KR')}<span className="text-sm font-semibold text-muted ml-1">품목</span>
              </p>
              <p className="mt-0.5 text-xs text-muted">
                {s.base_day ? `${fmtDay(s.base_day)} 단가표 기준` : '아직 수집되지 않음'}
                {s.supplier === 'sajo' && ' · 부가세 별도가만 제공'}
              </p>
            </button>
          ))}
          <div className="surface px-5 py-4">
            <p className="text-xs font-semibold text-navy-900">
              단가 변동 {summary.changes.day && <span className="font-normal text-muted">· {fmtDay(summary.changes.day)}</span>}
            </p>
            {summary.changes.day ? (
              <>
                <div className="mt-2 flex items-baseline gap-4 tabular-nums">
                  <span className="text-red-600"><span className="text-xs">▲ 인상</span> <b className="text-xl">{summary.changes.up}</b></span>
                  <span className="text-navy-600"><span className="text-xs">▼ 인하</span> <b className="text-xl">{summary.changes.down}</b></span>
                  {summary.changes.new > 0 && <span className="text-muted"><span className="text-xs">신규</span> <b className="text-xl text-navy-900">{summary.changes.new}</b></span>}
                </div>
                {summary.changes.movers.length > 0 && (
                  <button onClick={() => setShowMovers(!showMovers)} className="mt-1.5 text-xs font-semibold text-navy-600 hover:underline">
                    {showMovers ? '접기' : '변동 큰 품목 보기'}
                  </button>
                )}
              </>
            ) : (
              <p className="mt-2 text-sm text-muted leading-6">이틀 이상 수집되면 전날 대비 단가 변동이 여기에 표시됩니다.</p>
            )}
          </div>
        </section>
      )}

      {showMovers && summary?.changes?.movers?.length > 0 && (
        <section className="surface mb-5 divide-y divide-navy-100">
          {summary.changes.movers.map((m) => (
            <button key={m.supplier + m.item_cd} onClick={() => setOpen({ supplier: m.supplier, item_cd: m.item_cd })}
              className="w-full flex items-center gap-3 px-5 py-2.5 text-left hover:bg-navy-50/50">
              <SupBadge sup={m.supplier} short />
              <span className="flex-1 min-w-0 truncate text-sm text-navy-900">{m.item_nm}</span>
              <span className="text-xs text-muted tabular-nums hidden sm:inline">{won(m.prev_price)} → <b className="text-navy-900">{won(m.unit_price)}</b></span>
              <Change c={{ pct: m.pct, prev: m.prev_price, now: m.unit_price, on: m.changed_on }} compact />
            </button>
          ))}
        </section>
      )}

      {/* 검색 */}
      <section className="surface p-4 sm:p-5 mb-5">
        <div className="relative">
          <svg viewBox="0 0 24 24" className="w-5 h-5 absolute left-4 top-1/2 -translate-y-1/2 text-navy-400" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4-4" />
          </svg>
          <input ref={inputRef} value={input} onChange={(e) => setInput(e.target.value)} autoFocus
            placeholder="식재료 이름으로 검색 (예: 애호박, 닭가슴살 냉장, 연두부)"
            className="form-input pl-12 pr-10 py-3.5 text-base rounded-2xl" />
          {input && (
            <button onClick={() => setInput('')} aria-label="지우기"
              className="absolute right-3 top-1/2 -translate-y-1/2 w-7 h-7 rounded-full text-muted hover:bg-navy-50">✕</button>
          )}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted mr-1">자주 찾는</span>
          {QUICK.map((w) => (
            <button key={w} onClick={() => pick(w)}
              className={`px-2.5 py-1 rounded-full text-xs border transition ${q === w ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-navy-100 text-navy-700 hover:border-navy-300'}`}>{w}</button>
          ))}
          <span className="w-px h-4 bg-navy-100 mx-1" />
          {TAGS.map((t) => (
            <button key={t.id} onClick={() => setTag(tag === t.id ? '' : t.id)} title={t.hint}
              className={`px-2.5 py-1 rounded-full text-xs font-semibold border transition ${tag === t.id ? 'bg-teal-600 text-white border-teal-600' : 'bg-teal-50 border-teal-200 text-teal-800 hover:border-teal-400'}`}>
              {t.label}
            </button>
          ))}
        </div>

        {/* 필터 한 줄 */}
        <div className="mt-4 pt-4 border-t border-navy-100 flex flex-wrap items-center gap-2">
          <Seg value={supplier} onChange={setSupplier} options={[['', '전체'], ['hgreenfood', '현대그린푸드'], ['sajo', '사조']]} />
          <Seg value={storage} onChange={setStorage} options={[['', '보관 전체'], ...STORAGE.map((s) => [s, s])]} />
          <Seg value={origin} onChange={setOrigin} options={[['', '원산지 전체'], ['국산', '국산'], ['수입', '수입']]} />
          <select value={category} onChange={(e) => setCategory(e.target.value)} className="form-select w-auto py-1.5 text-xs">
            <option value="">분류 전체</option>
            {(summary?.categories || []).map((c) => <option key={c} value={c}>{c} (현대만)</option>)}
          </select>
          <div className="ml-auto flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-xs text-navy-700 cursor-pointer select-none">
              <input type="checkbox" checked={vat} onChange={(e) => setVat(e.target.checked)} className="accent-navy-600" />부가세 포함
            </label>
            <select value={sort} onChange={(e) => setSort(e.target.value)} className="form-select w-auto py-1.5 text-xs">
              <option value="relevance">정확도순</option>
              <option value="per_kg">kg당 낮은 가격순</option>
              <option value="price">단가 낮은순</option>
              <option value="name">이름순</option>
            </select>
          </div>
        </div>
      </section>

      {!searching ? (
        <Empty icon="solution" title="찾는 식재료를 검색해 보세요"
          desc="두 공급사의 같은 식재료를 한 화면에서 비교합니다. 띄어쓰기로 단어를 더하면 좁혀집니다(예: '닭가슴살 냉장'). '부드러운 식감'으로 다짐·무스·퓨레 제품만 모아 볼 수도 있습니다." />
      ) : !res && loading ? (
        <div className="surface p-12 text-center text-muted">찾는 중…</div>
      ) : res && res.total === 0 ? (
        <Empty icon="record" title="조건에 맞는 품목이 없습니다"
          desc={anyFilter ? '필터를 줄이거나 다른 이름으로 검색해 보세요. 사조는 분류 정보가 없어 분류 필터를 고르면 제외됩니다.' : '다른 이름으로 검색해 보세요. 예: 계란 → 란, 쇠고기 → 우육·소고기'} />
      ) : res && (
        <>
          <BestCompare best={res.best} pk={pk} onOpen={setOpen} />

          <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2">
            <p className="text-sm text-navy-900">
              <b className="tabular-nums">{res.total.toLocaleString('ko-KR')}</b>개 품목
              {Object.entries(res.counts || {}).filter(([, n]) => n).map(([s, n]) => (
                <span key={s} className="ml-3 text-xs text-muted"><SupBadge sup={s} short /> {n}</span>
              ))}
            </p>
            {res.truncated && <p className="text-xs text-warning">결과가 많아 일부만 보여줍니다. 단어를 더해 좁혀 보세요.</p>}
          </div>

          {/* 데스크톱 표 */}
          <div className="surface overflow-hidden hidden md:block">
            <table className="w-full text-sm">
              <thead className="bg-navy-50/60 text-[11px] text-muted">
                <tr>
                  <th className="text-left font-semibold px-4 py-2.5 w-[110px]">공급사</th>
                  <th className="text-left font-semibold px-2 py-2.5">품목</th>
                  <th className="text-left font-semibold px-2 py-2.5 w-[180px]">규격</th>
                  <th className="text-right font-semibold px-2 py-2.5 w-[110px]">단가{vat ? '' : '(별도)'}</th>
                  <th className="text-right font-semibold px-4 py-2.5 w-[120px]">kg당 환산</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-navy-100">
                {res.items.map((it) => <Row key={it.supplier + it.item_cd} it={it} pk={pk} pp={pp} best={res.best} onOpen={setOpen} />)}
              </tbody>
            </table>
          </div>

          {/* 모바일 카드 */}
          <div className="md:hidden space-y-2">
            {res.items.map((it) => <Card key={it.supplier + it.item_cd} it={it} pk={pk} pp={pp} onOpen={setOpen} />)}
          </div>

          {res.items.length < res.total && (
            <div className="mt-4 text-center">
              <button onClick={() => fetchPage(res.items.length)} disabled={loading} className="btn-secondary">
                {loading ? '불러오는 중…' : `더 보기 (${(res.total - res.items.length).toLocaleString('ko-KR')}개 남음)`}
              </button>
            </div>
          )}
          <p className="mt-5 text-[11px] leading-5 text-muted">
            kg당 환산은 규격 표기(예: 1.56Kg, 380g, 500G*10EA)에서 읽은 포장 중량으로 계산한 참고값이며, 표기를 읽을 수 없는 품목은 '—'로 둡니다.
            사조 단가는 부가세 별도가만 제공돼 과세 품목은 10%를 더해 계산했습니다(≈ 표시).
          </p>
        </>
      )}

      {open && <ItemPanel ref_={open} vat={vat} onClose={() => setOpen(null)} />}
    </CareLayout>
  )
}

function BestCompare({ best, pk, onOpen }) {
  const entries = Object.keys(SUP).map((s) => [s, best?.[s]])
  if (!entries.some(([, b]) => b)) return null
  const vals = entries.map(([, b]) => b?.[pk]).filter((v) => v != null)
  const min = Math.min(...vals)
  return (
    <section className="mb-4">
      <p className="text-[11px] font-semibold text-muted mb-1.5">kg당 최저가 비교 <span className="font-normal">· 검색어와 가장 가까운 품목들 중</span></p>
      <div className="grid gap-2 sm:grid-cols-2">
        {entries.map(([s, b]) => (
          <button key={s} disabled={!b} onClick={() => b && onOpen(b)}
            className={`text-left rounded-2xl border px-4 py-3 transition ${b ? 'bg-white hover:border-navy-300' : 'bg-navy-50/40'} ${b && b[pk] === min && vals.length > 1 ? 'border-navy-600' : 'border-navy-100'}`}>
            <div className="flex items-center justify-between">
              <SupBadge sup={s} />
              {b && b[pk] === min && vals.length > 1 && <span className="badge bg-navy-600 text-white">더 저렴</span>}
            </div>
            {b ? (
              <>
                <p className="mt-1.5 text-xl font-extrabold text-navy-900 tabular-nums">{won(b[pk])}<span className="text-xs font-semibold text-muted ml-1">/kg{b.tax_estimated ? ' ≈' : ''}</span></p>
                <p className="mt-0.5 text-xs text-muted truncate">{b.item_nm} · {b.spec}</p>
              </>
            ) : <p className="mt-2 text-xs text-muted">비교할 수 있는 품목이 없습니다</p>}
          </button>
        ))}
      </div>
    </section>
  )
}

function Badges({ it }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {it.storage && <span className={`badge px-1.5 py-0 text-[10.5px] ${STORAGE_STYLE[it.storage] || 'bg-slate-100 text-slate-600'}`}>{it.storage}</span>}
      {it.origin && <span className="badge px-1.5 py-0 text-[10.5px] bg-white border border-navy-100 text-navy-700">{it.origin}</span>}
      {it.tax_type === '면세' && <span className="badge px-1.5 py-0 text-[10.5px] bg-white border border-navy-100 text-muted">면세</span>}
      {it.lead_days != null && (
        <span className={`badge px-1.5 py-0 text-[10.5px] ${it.lead_days >= 3 ? 'bg-amber-50 text-amber-700' : 'bg-white border border-navy-100 text-muted'}`}
          title={`최소 발주: ${it.min_order_day}`}>{it.lead_days}일 전 발주</span>
      )}
      {it.stale && <span className="badge px-1.5 py-0 text-[10.5px] bg-slate-100 text-slate-500">단종 의심</span>}
    </span>
  )
}

function Row({ it, pk, pp, onOpen }) {
  const { name, attrs } = splitName(it.item_nm)
  return (
    <tr onClick={() => onOpen(it)} className="cursor-pointer hover:bg-navy-50/40">
      <td className="px-4 py-3 align-top"><SupBadge sup={it.supplier} /></td>
      <td className="px-2 py-3 align-top">
        <p className="font-semibold text-navy-900 leading-snug">{name}{attrs && <span className="ml-1.5 font-normal text-xs text-muted">{attrs}</span>}</p>
        <div className="mt-1"><Badges it={it} /></div>
      </td>
      <td className="px-2 py-3 align-top text-xs text-navy-700 break-all">{it.spec}<span className="text-muted"> / {it.unit}</span></td>
      <td className="px-2 py-3 align-top text-right tabular-nums">
        <p className="font-semibold text-navy-900">{won(it[pp])}{it.tax_estimated && pp === 'unit_price_tax' ? <span className="text-muted font-normal"> ≈</span> : ''}</p>
        <Change c={it.change} compact />
      </td>
      <td className="px-4 py-3 align-top text-right tabular-nums">
        {it[pk] != null
          ? <p className="font-bold text-navy-900">{won(it[pk])}<span className="block text-[10.5px] font-normal text-muted">{it.per_unit_label}</span></p>
          : <span className="text-muted">—</span>}
      </td>
    </tr>
  )
}

function Card({ it, pk, pp, onOpen }) {
  const { name, attrs } = splitName(it.item_nm)
  return (
    <button onClick={() => onOpen(it)} className="surface w-full text-left px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <SupBadge sup={it.supplier} />
        <Change c={it.change} compact />
      </div>
      <p className="mt-1.5 font-semibold text-navy-900 leading-snug">{name}</p>
      {attrs && <p className="text-xs text-muted">{attrs}</p>}
      <p className="mt-1 text-xs text-navy-700">{it.spec} / {it.unit}</p>
      <div className="mt-2 flex items-end justify-between gap-2">
        <Badges it={it} />
        <div className="text-right tabular-nums shrink-0">
          <p className="font-bold text-navy-900">{won(it[pp])}</p>
          {it[pk] != null && <p className="text-[11px] text-muted">{it.per_unit_label} {won(it[pk])}</p>}
        </div>
      </div>
    </button>
  )
}

function ItemPanel({ ref_, vat, onClose }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState('')
  useEffect(() => {
    setData(null); setErr('')
    api.get(`/prices/item/${ref_.supplier}/${encodeURIComponent(ref_.item_cd)}`)
      .then((r) => setData(r.data)).catch((e) => setErr(errMsg(e)))
  }, [ref_.supplier, ref_.item_cd])
  useEffect(() => {
    const k = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const it = data?.item
  const pk = vat ? 'per_kg_tax' : 'per_kg'
  const pp = vat ? 'unit_price_tax' : 'unit_price'
  return (
    <div className="fixed inset-0 z-40 no-print">
      <div className="absolute inset-0 bg-navy-950/30" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-lift overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-navy-100 px-5 py-3 flex items-center justify-between">
          <SupBadge sup={ref_.supplier} />
          <button onClick={onClose} className="w-8 h-8 rounded-full text-muted hover:bg-navy-50" aria-label="닫기">✕</button>
        </div>
        {err && <p className="m-5 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}
        {!it && !err && <p className="p-10 text-center text-muted">불러오는 중…</p>}
        {it && (
          <div className="px-5 py-5">
            <h2 className="text-lg font-extrabold text-navy-900 leading-snug">{it.item_nm}</h2>
            {it.category && <p className="mt-1 text-xs text-muted">{it.category}</p>}
            <div className="mt-2"><Badges it={it} /></div>

            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-2xl bg-navy-50/60 px-4 py-3">
                <p className="text-[11px] text-muted">단가 {vat ? '(부가세 포함)' : '(부가세 별도)'}</p>
                <p className="mt-1 text-xl font-extrabold text-navy-900 tabular-nums">{won(it[pp])}{it.tax_estimated && vat ? <span className="text-xs text-muted"> ≈</span> : ''}</p>
                <p className="text-[11px] text-muted">{it.unit} 기준</p>
              </div>
              <div className="rounded-2xl bg-navy-50/60 px-4 py-3">
                <p className="text-[11px] text-muted">{it.per_unit_label} 환산</p>
                <p className="mt-1 text-xl font-extrabold text-navy-900 tabular-nums">{won(it[pk])}</p>
                <p className="text-[11px] text-muted">{it.pack_g ? `포장 ${it.pack_g >= 1000 ? `${+(it.pack_g / 1000).toFixed(2)}kg` : `${it.pack_g}g`} 기준` : '규격에서 중량을 읽지 못함'}</p>
              </div>
            </div>

            <dl className="mt-5 text-sm divide-y divide-navy-100 border-y border-navy-100">
              {[
                ['규격', it.spec], ['단위', it.unit], ['원산지', it.origin], ['과세', it.tax_type],
                ['최소 발주', it.min_order_day], ['단품코드', it.item_cd], ['단가표 기준일', fmtDay(it.last_seen)],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="flex gap-3 py-2"><dt className="w-24 shrink-0 text-muted">{k}</dt><dd className="text-navy-900 break-all">{v}</dd></div>
              ))}
            </dl>
            {it.stale && <p className="mt-3 text-xs rounded-xl bg-slate-50 text-slate-600 px-3 py-2">최근 단가표에 없는 품목입니다. 단종됐거나 발주가 막혔을 수 있어요.</p>}

            <p className="mt-6 text-sm font-bold text-navy-900">단가 추이 <span className="text-xs font-normal text-muted">공급가(부가세 별도)</span></p>
            <PriceChart history={data.history} current={it.unit_price} today={it.last_seen} />
          </div>
        )}
      </aside>
    </div>
  )
}

// 단가는 바뀐 날까지 유지되므로 계단형 선으로 그린다. 마우스를 올리면 그 시점 단가를 보여준다.
function PriceChart({ history, current, today }) {
  const [hover, setHover] = useState(null)
  const pts = useMemo(() => {
    const out = []
    for (const h of history || []) {
      if (h.unit_price == null) continue
      out.push({ d: h.changed_on, v: +h.unit_price, prev: h.prev_price != null ? +h.prev_price : null })
    }
    if (out.length && today && today > out[out.length - 1].d) out.push({ d: today, v: current ?? out[out.length - 1].v, tail: true })
    return out
  }, [history, current, today])

  const changes = (history || []).filter((h) => h.change_type === 'changed')
  if (pts.length < 2 || changes.length === 0) {
    return <p className="mt-2 text-sm text-muted leading-6 rounded-xl bg-navy-50/50 px-4 py-3">
      {pts.length ? `${fmtDay(pts[0].d)}부터 단가 변동이 없습니다.` : '아직 기록이 없습니다.'} 단가가 바뀌면 여기에 추이가 쌓입니다.
    </p>
  }

  const W = 380, H = 150, L = 8, R = 8, T = 14, B = 22
  const t0 = new Date(pts[0].d).getTime(), t1 = new Date(pts[pts.length - 1].d).getTime() || t0 + 1
  const vs = pts.map((p) => p.v)
  let lo = Math.min(...vs), hi = Math.max(...vs)
  const pad = (hi - lo) * 0.25 || hi * 0.05 || 1
  lo -= pad; hi += pad
  const x = (d) => L + ((new Date(d).getTime() - t0) / Math.max(1, t1 - t0)) * (W - L - R)
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
  let path = `M${x(pts[0].d)},${y(pts[0].v)}`
  for (let i = 1; i < pts.length; i++) path += ` H${x(pts[i].d)} V${y(pts[i].v)}`

  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const px = ((e.clientX - r.left) / r.width) * W
    let idx = 0
    for (let i = 0; i < pts.length; i++) if (x(pts[i].d) <= px) idx = i
    setHover({ i: idx, px: Math.min(Math.max(px, L), W - R) })
  }
  const hp = hover && pts[hover.i]

  return (
    <div className="mt-2 relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseMove={onMove} onMouseLeave={() => setHover(null)}
        role="img" aria-label="단가 추이 그래프">
        <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="#d7e3f6" />
        <path d={path} fill="none" stroke="#1151b8" strokeWidth="2" strokeLinejoin="round" />
        {pts.filter((p) => !p.tail).map((p) => <circle key={p.d} cx={x(p.d)} cy={y(p.v)} r="4" fill="#1151b8" stroke="#fff" strokeWidth="2" />)}
        <text x={L} y={H - 6} fontSize="10" fill="#64748b">{fmtDay(pts[0].d)}</text>
        <text x={W - R} y={H - 6} fontSize="10" fill="#64748b" textAnchor="end">{fmtDay(pts[pts.length - 1].d)}</text>
        {hp && <line x1={hover.px} x2={hover.px} y1={T - 6} y2={H - B} stroke="#7fa1de" strokeDasharray="3 3" />}
      </svg>
      {hp && (
        <div className="absolute top-0 pointer-events-none rounded-lg bg-navy-900 text-white text-[11px] px-2.5 py-1.5 shadow-lift tabular-nums"
          style={{ left: `${(hover.px / W) * 100}%`, transform: `translateX(${hover.px > W / 2 ? '-105%' : '5%'})` }}>
          <p className="text-white/70">{fmtDay(hp.d)}{hp.tail ? ' (현재)' : ''}</p>
          <p className="font-semibold">{won(hp.v)}</p>
        </div>
      )}
      <ul className="mt-3 space-y-1 text-xs">
        {[...changes].reverse().slice(0, 8).map((h) => {
          const p0 = +h.prev_price, p1 = +h.unit_price
          const pct = p0 ? Math.round(((p1 - p0) / p0) * 1000) / 10 : 0
          return (
            <li key={h.changed_on} className="flex items-center gap-2 tabular-nums">
              <span className="w-16 text-muted">{fmtDay(h.changed_on)}</span>
              <span className="text-navy-700">{won(p0)} → <b className="text-navy-900">{won(p1)}</b></span>
              <Change c={{ pct, prev: p0, now: p1, on: h.changed_on }} compact />
            </li>
          )
        })}
      </ul>
    </div>
  )
}

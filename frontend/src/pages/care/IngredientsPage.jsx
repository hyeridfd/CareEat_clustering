import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { errMsg } from '../../components/care/CareUI'

// ─────────────────────────── 표시 규칙 ───────────────────────────
// 공급사 색은 검증된 2색(색약 ΔE 9.7, 일반 ΔE 23.4). 항상 이름과 같이 써서 색만으로 구분하지 않는다.
const SUP = {
  hgreenfood: { label: '현대그린푸드', short: '현대', color: '#0f9d76', tint: '#e7f5f0' },
  sajo: { label: '사조푸디스트', short: '사조', color: '#d97706', tint: '#fdf3e6' },
}
const SUP_KEYS = Object.keys(SUP)
const UP = '#dc2626'      // 단가 인상 (구매자에게 불리) — 항상 ▲ 와 같이
const DOWN = '#1151b8'    // 단가 인하 — 항상 ▼ 와 같이
const QUICK = ['두부', '계란', '닭가슴살', '고등어', '애호박', '단호박', '연어', '다짐육', '순두부', '바나나']
const TAGS = [
  { id: 'soft', label: '부드러운 식감', hint: '다짐·무스·퓨레·연육·고령친화 제품' },
  { id: 'lowsalt', label: '저염·저당', hint: '저염·저당·무염·저나트륨 제품' },
]
const CATS = [
  { id: '농산품', icon: 'leaf', desc: '야채·청과·양곡' },
  { id: '축산품', icon: 'meat', desc: '우육·돈육·계육' },
  { id: '수산품', icon: 'fish', desc: '어패류·해조류' },
  { id: '공산품', icon: 'box', desc: '가공·조미·유제품' },
]
const PAGE = 40
const WD = ['일', '월', '화', '수', '목', '금', '토']

const won = (v) => (v == null ? '—' : `${Math.round(v).toLocaleString('ko-KR')}원`)
const short = (v) => (v >= 10000 ? `${+(v / 10000).toFixed(v >= 100000 ? 0 : 1)}만` : v >= 1000 ? `${+(v / 1000).toFixed(1)}천` : `${v}`)
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
// '(C)양배추(상품,실온,겉잎제거,국산)' → 이름 '양배추', 속성 '겉잎제거' (보관·원산지는 배지로 따로 보여줌)
function splitName(nm = '') {
  const prefix = (nm.match(/^(\([^)]*\)|\[[^\]]*\])/) || [''])[0]
  const rest = nm.slice(prefix.length)
  const i = rest.indexOf('(')
  if (i <= 0) return { name: rest || nm, attrs: '' }
  const attrs = rest.slice(i + 1).replace(/\)$/, '').split(',').map((s) => s.trim())
    .filter((s) => s && !['냉장', '냉동', '실온', '상온', '국산', '수입', '상품'].includes(s)).join(' · ')
  return { name: rest.slice(0, i), attrs }
}

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width))
    ro.observe(ref.current)
    setW(ref.current.getBoundingClientRect().width)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

// kg당 가격은 1천~수십만 원까지 퍼져 있어 로그 눈금으로 그린다.
const TICKS = [500, 1000, 2000, 5000, 10000, 20000, 50000, 100000, 200000, 500000]
function logScale(lo, hi, x0, x1) {
  const a = Math.log10(Math.max(lo, 1)), b = Math.log10(Math.max(hi, lo * 1.5, 2))
  const f = (v) => x0 + ((Math.log10(Math.max(v, 1)) - a) / (b - a)) * (x1 - x0)
  f.ticks = TICKS.filter((t) => t >= lo && t <= hi)
  return f
}

// ─────────────────────────── 작은 조각 ───────────────────────────
function Icon({ name, className = 'w-4 h-4' }) {
  const p = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }
  const s = {
    search: <><circle cx="11" cy="11" r="6.5" {...p} /><path d="M20 20l-4-4" {...p} /></>,
    snow: <><path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9" {...p} /><path d="M9.5 4.5L12 7l2.5-2.5M9.5 19.5L12 17l2.5 2.5" {...p} /></>,
    drop: <path d="M12 3.5s6 6.4 6 10.5a6 6 0 0 1-12 0c0-4.1 6-10.5 6-10.5z" {...p} />,
    sun: <><circle cx="12" cy="12" r="4" {...p} /><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4" {...p} /></>,
    leaf: <><path d="M5 19c0-8 5-13 14-14 0 9-5 14-13 14" {...p} /><path d="M5 19l7-7" {...p} /></>,
    meat: <><path d="M14.5 4.5a6 6 0 0 1 4.9 8.6c-1.4 3-5.4 4.6-8.4 3.3l-3.5 3.5a1.8 1.8 0 1 1-2.5-2.5l3.5-3.5c-1.3-3 .3-7 3.3-8.4.9-.4 1.8-.6 2.7-.6z" {...p} /></>,
    fish: <><path d="M3 12c3-4.5 7-6 11-6 3 0 5.5 2 7 6-1.5 4-4 6-7 6-4 0-8-1.5-11-6z" {...p} /><path d="M3 12l-1-3M3 12l-1 3" {...p} /><circle cx="16" cy="11" r="1" fill="currentColor" /></>,
    box: <><path d="M3.5 7.5L12 3l8.5 4.5v9L12 21l-8.5-4.5z" {...p} /><path d="M3.5 7.5L12 12l8.5-4.5M12 12v9" {...p} /></>,
    clock: <><circle cx="12" cy="12" r="8" {...p} /><path d="M12 8v4l2.5 2" {...p} /></>,
    x: <path d="M6 6l12 12M18 6L6 18" {...p} />,
  }
  return <svg viewBox="0 0 24 24" className={className} aria-hidden="true">{s[name]}</svg>
}

const STORAGE = {
  냉장: { icon: 'drop', cls: 'text-sky-700 bg-sky-50' },
  냉동: { icon: 'snow', cls: 'text-indigo-700 bg-indigo-50' },
  실온: { icon: 'sun', cls: 'text-stone-600 bg-stone-100' },
}

function SupTag({ sup, short: sh, className = '' }) {
  const s = SUP[sup]
  if (!s) return null
  return (
    <span className={`inline-flex items-center gap-1.5 text-xs font-semibold text-navy-900 whitespace-nowrap ${className}`}>
      <span className="w-2.5 h-2.5 rounded-full ring-2 ring-white" style={{ background: s.color }} />{sh ? s.short : s.label}
    </span>
  )
}

function Change({ c }) {
  if (!c || !c.pct) return null
  const up = c.pct > 0
  return (
    <span className="inline-flex items-center gap-0.5 text-[11px] font-bold tabular-nums" style={{ color: up ? UP : DOWN }}
      title={`${fmtDay(c.on)} ${won(c.prev)} → ${won(c.now)}`}>
      {up ? '▲' : '▼'}{Math.abs(c.pct)}%
    </span>
  )
}

function Seg({ value, onChange, options }) {
  return (
    <div className="inline-flex rounded-xl bg-white border border-navy-100 p-0.5">
      {options.map(([v, label]) => (
        <button key={label} onClick={() => onChange(v)}
          className={`px-3 py-1.5 rounded-[10px] text-xs font-semibold transition whitespace-nowrap ${
            value === v ? 'bg-navy-900 text-white' : 'text-muted hover:text-navy-700'}`}>{label}</button>
      ))}
    </div>
  )
}

// ─────────────────────────── 페이지 ───────────────────────────
export default function IngredientsPage() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const [input, setInput] = useState(q)
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
  const [open, setOpen] = useState(null)
  const reqId = useRef(0)

  useEffect(() => {
    api.get('/prices/summary').then((r) => setSummary(r.data)).catch((e) => setErr(errMsg(e, '단가 정보를 불러오지 못했습니다.')))
  }, [])

  // 입력이 0.3초 멈추면 검색. 주소(?q=)에 남겨 새로고침·공유해도 그대로 보인다.
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
        setRes((prev) => (offset && prev ? { ...prev, ...r.data, items: [...prev.items, ...r.data.items], dist: prev.dist, stats: prev.stats } : r.data))
      })
      .catch((e) => id === reqId.current && setErr(errMsg(e)))
      .finally(() => id === reqId.current && setLoading(false))
  }
  useEffect(() => {
    if (!q && !tag && !category) { setRes(null); return }
    fetchPage(0)
  }, [JSON.stringify(filters)]) // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (w) => { setInput(w); setTag('') }
  const reset = () => { setInput(''); setTag(''); setCategory(''); setSupplier(''); setStorage(''); setOrigin('') }
  const pk = vat ? 'per_kg_tax' : 'per_kg'
  const pp = vat ? 'unit_price_tax' : 'unit_price'
  const searching = !!(q || tag || category)
  const updated = summary?.suppliers?.map((s) => s.updated_at).filter(Boolean).sort().pop()

  // 결과 목록의 kg당 막대는 분포 그래프와 같은 눈금을 쓴다
  const scaleDomain = useMemo(() => {
    const vs = (res?.dist || []).map((d) => d.v)
    return vs.length ? [Math.min(...vs), Math.max(...vs)] : null
  }, [res?.dist])

  return (
    <CareLayout title="식자재" subtitle="두 공급사의 계약 단가를 매일 아침 반영해, 같은 식재료를 kg당 가격으로 맞춰 비교합니다.">
      {err && <p className="mb-4 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}

      {/* ── 검색 영역 ── */}
      <section className="relative overflow-hidden rounded-2xl bg-navy-grad text-white px-5 sm:px-7 pt-5 pb-5 mb-5 shadow-card">
        <div className="pointer-events-none absolute -right-16 -top-20 w-72 h-72 rounded-full bg-white/[0.06]" />
        <div className="pointer-events-none absolute right-24 -bottom-24 w-56 h-56 rounded-full bg-sky-300/10" />
        <div className="relative flex flex-wrap items-center gap-x-2 gap-y-2 text-[12px] text-white/80">
          {(summary?.suppliers || []).map((s) => (
            <button key={s.supplier} onClick={() => setSupplier(supplier === s.supplier ? '' : s.supplier)}
              title="이 공급사만 보기"
              className={`inline-flex items-center gap-2 rounded-full pl-2 pr-3 py-1 transition ${supplier === s.supplier ? 'bg-white text-navy-900' : 'bg-white/10 hover:bg-white/15'}`}>
              <span className="w-2.5 h-2.5 rounded-full ring-2 ring-white/80" style={{ background: SUP[s.supplier]?.color }} />
              <b className="font-semibold">{s.label}</b>
              <span className="tabular-nums opacity-80">{s.items.toLocaleString('ko-KR')}품목</span>
            </button>
          ))}
          {updated && (
            <span className="inline-flex items-center gap-1.5 ml-auto"><Icon name="clock" className="w-3.5 h-3.5" />
              {fmtDay(updated)} {fmtTime(updated)} 반영</span>
          )}
        </div>

        <div className="relative mt-4">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-navy-400"><Icon name="search" className="w-5 h-5" /></span>
          <input value={input} onChange={(e) => setInput(e.target.value)} autoFocus
            placeholder="찾는 식재료를 입력하세요   예) 애호박 · 닭가슴살 냉장 · 연두부"
            className="w-full rounded-2xl border-0 bg-white pl-12 pr-12 py-4 text-[16px] text-ink placeholder:text-slate-400 shadow-lift focus:outline-none focus:ring-4 focus:ring-sky-300/40" />
          {(input || searching) && (
            <button onClick={reset} aria-label="검색 지우기"
              className="absolute right-3 top-1/2 -translate-y-1/2 w-8 h-8 inline-flex items-center justify-center rounded-full text-muted hover:bg-navy-50">
              <Icon name="x" />
            </button>
          )}
        </div>

        <div className="relative mt-3.5 flex flex-wrap items-center gap-1.5">
          {QUICK.map((w) => (
            <button key={w} onClick={() => pick(w)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition ${q === w ? 'bg-white text-navy-900' : 'bg-white/10 text-white/90 hover:bg-white/20'}`}>{w}</button>
          ))}
          <span className="w-px h-4 bg-white/25 mx-1.5" />
          {TAGS.map((t) => (
            <button key={t.id} onClick={() => setTag(tag === t.id ? '' : t.id)} title={t.hint}
              className={`px-3 py-1 rounded-full text-xs font-semibold transition ${tag === t.id ? 'bg-teal-300 text-navy-950' : 'bg-teal-300/15 text-teal-100 ring-1 ring-teal-200/40 hover:bg-teal-300/25'}`}>
              {t.label}
            </button>
          ))}
        </div>
      </section>

      {!searching ? (
        <Home summary={summary} onCategory={(c) => setCategory(c)} onOpen={setOpen} />
      ) : (
        <>
          {/* ── 필터 ── */}
          <div className="flex items-center gap-2 mb-4 overflow-x-auto md:flex-wrap md:overflow-visible -mx-5 px-5 md:mx-0 md:px-0 pb-1 [&>*]:shrink-0">
            <Seg value={supplier} onChange={setSupplier} options={[['', '전체'], ['hgreenfood', '현대그린푸드'], ['sajo', '사조']]} />
            <Seg value={storage} onChange={setStorage} options={[['', '보관 전체'], ['냉장', '냉장'], ['냉동', '냉동'], ['실온', '실온']]} />
            <Seg value={origin} onChange={setOrigin} options={[['', '원산지 전체'], ['국산', '국산'], ['수입', '수입']]} />
            <select value={category} onChange={(e) => setCategory(e.target.value)} className="form-select w-auto py-1.5 text-xs">
              <option value="">분류 전체</option>
              {CATS.map((c) => <option key={c.id} value={c.id}>{c.id}</option>)}
            </select>
            <div className="ml-auto flex items-center gap-3">
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

          {!res && loading ? (
            <Skeleton />
          ) : res && res.total === 0 ? (
            <div className="surface p-12 text-center">
              <p className="font-bold text-navy-900">조건에 맞는 품목이 없습니다</p>
              <p className="mt-2 text-sm text-muted leading-6">필터를 줄이거나 다른 이름으로 검색해 보세요.<br />예: 쇠고기 → 우육·소고기</p>
              <button onClick={reset} className="btn-secondary mt-5">검색 초기화</button>
            </div>
          ) : res && (
            <div className={loading ? 'opacity-60 transition-opacity' : 'transition-opacity'}>
              <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr] mb-5">
                <DistChart dist={res.dist} stats={res.stats} onOpen={setOpen} />
                <Compare best={res.best} stats={res.stats} pk={pk} onOpen={setOpen} />
              </div>

              <div className="flex flex-wrap items-baseline justify-between gap-2 mb-2.5">
                <p className="text-sm text-navy-900">
                  <b className="tabular-nums text-base">{res.total.toLocaleString('ko-KR')}</b>개 품목
                  {SUP_KEYS.filter((s) => res.counts?.[s]).map((s) => (
                    <span key={s} className="ml-3 text-xs text-muted inline-flex items-center gap-1"><SupTag sup={s} short /> <span className="tabular-nums">{res.counts[s]}</span></span>
                  ))}
                </p>
                {res.truncated && <p className="text-xs text-warning">결과가 많아 일부만 보여줍니다. 단어를 더해 좁혀 보세요.</p>}
              </div>

              <div className="surface overflow-hidden">
                <div className="hidden md:grid grid-cols-[76px_1fr_150px_104px_170px] gap-3 px-4 py-2.5 bg-navy-50/60 text-[11px] font-semibold text-muted">
                  <span>공급사</span><span>품목</span><span>규격</span><span className="text-right">단가{vat ? '' : ' (별도)'}</span><span className="text-right">kg당 환산</span>
                </div>
                <ul className="divide-y divide-navy-100">
                  {res.items.map((it) => (
                    <ItemRow key={it.supplier + it.item_cd} it={it} pk={pk} pp={pp} domain={scaleDomain}
                      cheapest={SUP_KEYS.some((s) => res.best?.[s]?.item_cd === it.item_cd && res.best?.[s]?.supplier === it.supplier)}
                      onOpen={setOpen} />
                  ))}
                </ul>
              </div>

              {res.items.length < res.total && (
                <div className="mt-4 text-center">
                  <button onClick={() => fetchPage(res.items.length)} disabled={loading} className="btn-secondary">
                    {loading ? '불러오는 중…' : `더 보기 · ${(res.total - res.items.length).toLocaleString('ko-KR')}개 남음`}
                  </button>
                </div>
              )}
              <p className="mt-5 text-[11px] leading-5 text-muted">
                kg당 환산은 규격 표기(1.56Kg, 380g, 500G*10EA 등)에서 읽은 포장 중량으로 계산한 참고값입니다. 표기를 읽을 수 없는 품목은 '—'로 둡니다.
                사조는 부가세 별도가만 제공돼 과세 품목은 10%를 더해 계산했습니다(≈). 사조의 대·중분류는 현대그린푸드 분류를 학습해 품목명으로 추정한 값입니다.
              </p>
            </div>
          )}
        </>
      )}

      {open && <ItemPanel ref_={open} vat={vat} dist={res?.dist} onClose={() => setOpen(null)} />}
    </CareLayout>
  )
}

function Skeleton() {
  return (
    <div className="space-y-4 animate-pulse">
      <div className="grid gap-4 lg:grid-cols-[1.55fr_1fr]"><div className="surface h-56" /><div className="surface h-56" /></div>
      <div className="surface h-80" />
    </div>
  )
}

// ─────────────────────────── 검색 전 첫 화면 ───────────────────────────
function Home({ summary, onCategory, onOpen }) {
  const ch = summary?.changes
  return (
    <>
    <div className="grid gap-4 lg:grid-cols-[1fr_1.35fr]">
      <section className="surface p-5">
        <p className="text-sm font-bold text-navy-900">분류로 둘러보기</p>
        <p className="mt-0.5 text-xs text-muted">두 공급사 공통 · 사조는 품목명으로 자동 분류했어요</p>
        <div className="mt-4 grid grid-cols-2 gap-2.5">
          {CATS.map((c) => (
            <button key={c.id} onClick={() => onCategory(c.id)}
              className="group text-left rounded-2xl border border-navy-100 px-4 py-3.5 hover:border-navy-300 hover:bg-navy-50/40 transition">
              <span className="inline-flex w-9 h-9 items-center justify-center rounded-xl bg-navy-50 text-navy-600 group-hover:bg-navy-600 group-hover:text-white transition">
                <Icon name={c.icon} className="w-5 h-5" />
              </span>
              <p className="mt-2.5 text-sm font-bold text-navy-900">{c.id}</p>
              <p className="text-[11px] text-muted">{c.desc}</p>
            </button>
          ))}
        </div>
        <div className="mt-4 rounded-xl bg-teal-50/70 px-4 py-3 text-xs leading-5 text-teal-900">
          <b>Tip</b> 띄어쓰기로 단어를 더하면 좁혀집니다 — '닭가슴살 냉장', '두부 국산'.
          위의 <b>부드러운 식감</b>을 누르면 다짐·무스·퓨레 제품만 모아 볼 수 있어요.
        </div>
      </section>

      <section className="surface p-5">
        <p className="text-sm font-bold text-navy-900">단가 변동 {ch?.day && <span className="font-normal text-muted text-xs ml-1">{fmtDay(ch.day)} 반영분</span>}</p>
        {!summary ? (
          <div className="mt-4 h-48 rounded-xl bg-navy-50/60 animate-pulse" />
        ) : !ch?.day ? (
          <div className="mt-4 rounded-xl bg-navy-50/50 px-4 py-8 text-center text-sm text-muted leading-6">
            단가표가 이틀 이상 쌓이면<br />전날 대비 오르고 내린 품목이 여기에 그래프로 표시됩니다.
          </div>
        ) : (
          <>
            <div className="mt-3 grid grid-cols-3 gap-2">
              {[['▲ 인상', ch.up, UP], ['▼ 인하', ch.down, DOWN], ['신규', ch.new, '#07204d']].map(([k, n, c]) => (
                <div key={k} className="rounded-xl bg-navy-50/50 px-3 py-2.5">
                  <p className="text-[11px] font-semibold" style={{ color: c }}>{k}</p>
                  <p className="text-2xl font-extrabold tabular-nums text-navy-900">{n}<span className="text-xs font-semibold text-muted ml-0.5">건</span></p>
                </div>
              ))}
            </div>
            <Movers movers={ch.movers} onOpen={onOpen} />
          </>
        )}
      </section>
    </div>
    <TrendSection />
    </>
  )
}

// 변동률 막대: 가운데 0을 기준으로 인하는 왼쪽(파랑 ▼), 인상은 오른쪽(빨강 ▲)
function Movers({ movers = [], onOpen }) {
  const [hover, setHover] = useState(null)
  if (!movers.length) return <p className="mt-4 text-sm text-muted">변동 폭이 큰 품목이 없습니다.</p>
  const max = Math.max(...movers.map((m) => Math.abs(m.pct)), 1)
  return (
    <div className="mt-4">
      <p className="text-[11px] text-muted mb-1.5">변동 폭이 큰 품목 · 공급가 전날 대비</p>
      <ul className="space-y-0.5">
        {movers.slice(0, 10).map((m) => {
          const up = m.pct > 0
          const w = (Math.abs(m.pct) / max) * 50
          const key = m.supplier + m.item_cd
          return (
            <li key={key}>
              <button onClick={() => onOpen({ supplier: m.supplier, item_cd: m.item_cd })}
                onMouseEnter={() => setHover(key)} onMouseLeave={() => setHover(null)}
                className="w-full grid grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)_58px] items-center gap-3 rounded-lg px-2 py-1.5 text-left hover:bg-navy-50/60">
                <span className="min-w-0 flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: SUP[m.supplier]?.color }} title={SUP[m.supplier]?.label} />
                  <span className="truncate text-[13px] text-navy-900">{splitName(m.item_nm).name}</span>
                </span>
                <span className="relative h-4">
                  <span className="absolute left-1/2 top-[-2px] bottom-[-2px] w-px bg-navy-200" />
                  <span className="absolute top-0.5 h-3 rounded-[3px]"
                    style={{ background: up ? UP : DOWN, opacity: hover && hover !== key ? 0.35 : 0.9, width: `${Math.max(w, 1.5)}%`, [up ? 'left' : 'right']: '50%' }} />
                  {hover === key && (
                    <span className="absolute -top-7 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-navy-900 text-white text-[11px] px-2 py-0.5 tabular-nums z-10">
                      {won(m.prev_price)} → {won(m.unit_price)}
                    </span>
                  )}
                </span>
                <span className="text-right text-[12px] font-bold tabular-nums" style={{ color: up ? UP : DOWN }}>{up ? '▲' : '▼'}{Math.abs(m.pct)}%</span>
              </button>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// ─────────────────────────── 분포 그래프 ───────────────────────────
// 공급사마다 한 줄. 점 하나가 품목 하나(kg당 가격). 옅은 띠 = 가운데 50%, 굵은 세로선 = 중앙값.
function DistChart({ dist, stats, onOpen }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)
  const lanes = SUP_KEYS.filter((s) => stats?.[s])
  const empty = !dist?.length || !lanes.length
  const vs = empty ? [1000, 2000] : dist.map((d) => d.v)
  const lo = Math.min(...vs) * 0.85, hi = Math.max(...vs) * 1.15
  const W = Math.max(width, 280), L = 50, R = 16, LANE = 76, T = 8, B = 26
  const H = T + Math.max(lanes.length, 1) * LANE + B
  const x = logScale(lo, hi, L, W - R)
  const laneY = (s) => T + lanes.indexOf(s) * LANE + LANE / 2
  // 같은 값이 겹치지 않게 품목코드로 정한 세로 흔들기
  const jitter = (cd) => { let h = 7; for (const c of String(cd)) h = (h * 31 + c.charCodeAt(0)) % 100003; return ((h % 1000) / 1000 - 0.5) * (LANE * 0.52) }

  return (
    <section className="surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-bold text-navy-900">kg당 가격 분포</p>
        <p className="text-[11px] text-muted">점 = 품목 · 띠 = 가운데 50% · 세로선 = 중앙값</p>
      </div>
      <div ref={ref} className="relative mt-2">
        {empty ? (
          <p className="py-14 text-center text-sm text-muted">kg 단위로 환산할 수 있는 품목이 없어 분포를 그릴 수 없습니다.</p>
        ) : width > 0 && (
          <svg width={W} height={H} role="img" aria-label="공급사별 kg당 가격 분포">
            {x.ticks.map((t) => (
              <g key={t}>
                <line x1={x(t)} x2={x(t)} y1={T} y2={H - B} stroke="#eef3fb" />
                <text x={x(t)} y={H - 8} fontSize="10.5" fill="#64748b" textAnchor="middle">{short(t)}</text>
              </g>
            ))}
            {lanes.map((s) => {
              const st = stats[s], y = laneY(s), c = SUP[s].color
              return (
                <g key={s}>
                  <text x={0} y={y - 2} fontSize="12" fontWeight="700" fill="#07204d">{SUP[s].short}</text>
                  <text x={0} y={y + 13} fontSize="10.5" fill="#64748b">{st.n}개</text>
                  <rect x={x(st.p25)} width={Math.max(x(st.p75) - x(st.p25), 2)} y={y - LANE * 0.38} height={LANE * 0.76} rx="4" fill={SUP[s].tint} />
                  {dist.filter((d) => d.s === s).map((d) => {
                    const on = hover?.cd === d.cd && hover?.s === s
                    const cy = y + jitter(d.cd)
                    return (
                      <circle key={d.cd} cx={x(d.v)} cy={cy} r={on ? 6 : 4} fill={c}
                        fillOpacity={hover && !on ? 0.25 : 0.72} stroke="#fff" strokeWidth="1.5" style={{ cursor: 'pointer' }}
                        onMouseEnter={() => setHover({ ...d, px: x(d.v), py: cy })} onMouseLeave={() => setHover(null)}
                        onClick={() => onOpen({ supplier: s, item_cd: d.cd })} />
                    )
                  })}
                  <line x1={x(st.median)} x2={x(st.median)} y1={y - LANE * 0.44} y2={y + LANE * 0.44} stroke="#07204d" strokeWidth="2.5" strokeLinecap="round" />
                  <text x={x(st.median) + 5} y={y - LANE * 0.44 + 9} fontSize="10" fontWeight="700" fill="#07204d">{short(st.median)}</text>
                </g>
              )
            })}
          </svg>
        )}
        {hover && (
          <div className="absolute pointer-events-none z-10 w-56 rounded-xl bg-navy-900 text-white px-3 py-2 shadow-lift text-[11.5px] leading-snug"
            style={{ left: Math.min(Math.max(hover.px - 112, 0), W - 224), top: hover.py + 12 }}>
            <p className="font-semibold">{hover.nm}</p>
            <p className="text-white/65 mt-0.5 truncate">{hover.spec}</p>
            <p className="mt-1 tabular-nums"><b className="text-[13px]">{won(hover.v)}</b><span className="text-white/65"> /kg · {SUP[hover.s].label}</span></p>
          </div>
        )}
      </div>
      {!empty && (
        <div className="mt-3 pt-3 border-t border-navy-100 grid gap-1.5 text-[11.5px]">
          {lanes.map((s) => {
            const st = stats[s]
            return (
              <p key={s} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-muted tabular-nums">
                <SupTag sup={s} short className="w-12" />
                <span>대부분 <b className="text-navy-900 font-semibold">{won(st.p25)} ~ {won(st.p75)}</b>/kg</span>
                <span>중앙값 <b className="text-navy-900 font-semibold">{won(st.median)}</b></span>
                <span className="hidden sm:inline">전체 {won(st.min)} ~ {won(st.max)}</span>
              </p>
            )
          })}
        </div>
      )}
    </section>
  )
}

// ─────────────────────────── 공급사 비교 ───────────────────────────
function Compare({ best, stats, pk, onOpen }) {
  const lanes = SUP_KEYS.filter((s) => best?.[s] || stats?.[s])
  if (!lanes.length) return <section className="surface p-5 text-sm text-muted">비교할 수 있는 품목이 없습니다.</section>
  const mins = lanes.map((s) => best?.[s]?.[pk]).filter((v) => v != null)
  const lowest = mins.length > 1 ? Math.min(...mins) : null
  const meds = lanes.map((s) => stats?.[s]?.median).filter(Boolean)
  const maxMed = Math.max(...meds, 1)
  let insight = null
  if (stats?.hgreenfood && stats?.sajo) {
    const a = stats.hgreenfood.median, b = stats.sajo.median
    const cheaper = a <= b ? 'hgreenfood' : 'sajo'
    const diff = Math.round((1 - Math.min(a, b) / Math.max(a, b)) * 100)
    insight = diff >= 3
      ? <>검색 결과의 kg당 중앙값은 <b>{SUP[cheaper].short}</b>가 <b>{diff}%</b> 낮아요.</>
      : <>두 공급사의 kg당 중앙값이 비슷해요.</>
  }
  return (
    <section className="surface p-5 flex flex-col">
      <p className="text-sm font-bold text-navy-900">공급사별 최저가</p>
      <p className="text-[11px] text-muted">검색어와 가장 가까운 품목 중 kg당 가장 싼 것</p>
      <div className="mt-3 space-y-2.5 flex-1">
        {lanes.map((s) => {
          const b = best?.[s], st = stats?.[s]
          const win = b && lowest != null && b[pk] === lowest
          return (
            <button key={s} disabled={!b} onClick={() => b && onOpen(b)}
              className={`w-full text-left rounded-2xl border px-4 py-3 transition ${win ? 'border-navy-600 bg-navy-50/40' : 'border-navy-100 hover:border-navy-300'}`}>
              <div className="flex items-center justify-between gap-2">
                <SupTag sup={s} />
                {win && <span className="badge bg-navy-600 text-white">최저</span>}
              </div>
              {b ? (
                <>
                  <p className="mt-1 text-[22px] leading-tight font-extrabold text-navy-900 tabular-nums">
                    {won(b[pk])}<span className="text-xs font-semibold text-muted ml-1">/kg{b.tax_estimated ? ' ≈' : ''}</span>
                  </p>
                  <p className="text-[11.5px] text-muted truncate">{splitName(b.item_nm).name} · {b.spec}</p>
                </>
              ) : <p className="mt-1 text-xs text-muted">kg 환산 가능한 품목 없음</p>}
              {st && (
                <div className="mt-2.5">
                  <div className="flex justify-between text-[10.5px] text-muted"><span>중앙값</span><span className="tabular-nums">{won(st.median)}/kg</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-navy-50 overflow-hidden">
                    <div className="h-full rounded-full" style={{ width: `${(st.median / maxMed) * 100}%`, background: SUP[s].color }} />
                  </div>
                </div>
              )}
            </button>
          )
        })}
      </div>
      {insight && <p className="mt-3 text-xs text-navy-800 rounded-xl bg-navy-50/70 px-3 py-2">{insight}</p>}
    </section>
  )
}

// ─────────────────────────── 결과 한 줄 ───────────────────────────
function Badges({ it }) {
  const st = STORAGE[it.storage]
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {st && <span className={`badge gap-0.5 px-1.5 py-0 text-[10.5px] ${st.cls}`}><Icon name={st.icon} className="w-3 h-3" />{it.storage}</span>}
      {it.origin && <span className="badge px-1.5 py-0 text-[10.5px] bg-white border border-navy-100 text-navy-700">{it.origin}</span>}
      {it.tax_type === '면세' && <span className="badge px-1.5 py-0 text-[10.5px] bg-white border border-navy-100 text-muted">면세</span>}
      {it.lead_days != null && (
        <span className={`badge px-1.5 py-0 text-[10.5px] ${it.lead_days >= 3 ? 'bg-amber-50 text-amber-800' : 'bg-white border border-navy-100 text-muted'}`}
          title={`최소 발주: ${it.min_order_day}`}>D-{it.lead_days} 발주</span>
      )}
      {it.stale && <span className="badge px-1.5 py-0 text-[10.5px] bg-slate-100 text-slate-500">단종 의심</span>}
    </span>
  )
}

function KgBar({ v, domain, color }) {
  if (v == null || !domain) return null
  const x = logScale(domain[0] * 0.85, domain[1] * 1.15, 0, 100)
  return (
    <span className="mt-1 ml-auto block h-1 w-full max-w-[140px] rounded-full bg-navy-50 overflow-hidden" title="이 검색 결과 안에서의 kg당 가격 위치">
      <span className="block h-full rounded-full" style={{ width: `${Math.min(Math.max(x(v), 3), 100)}%`, background: color, opacity: 0.85 }} />
    </span>
  )
}

function ItemRow({ it, pk, pp, domain, cheapest, onOpen }) {
  const { name, attrs } = splitName(it.item_nm)
  const kg = it[pk]
  return (
    <li>
      <button onClick={() => onOpen(it)}
        className="relative w-full text-left px-4 py-3 hover:bg-navy-50/40 transition md:grid md:grid-cols-[76px_1fr_150px_104px_170px] md:gap-3 md:items-start">
        <span className="absolute left-0 top-3 bottom-3 w-[3px] rounded-r" style={{ background: SUP[it.supplier]?.color }} />
        <span className="hidden md:block pt-0.5"><SupTag sup={it.supplier} short /></span>
        <span className="block min-w-0">
          <span className="md:hidden mb-1 flex items-center justify-between"><SupTag sup={it.supplier} short /><Change c={it.change} /></span>
          <span className="block font-semibold text-navy-900 leading-snug">
            {name}{cheapest && <span className="badge bg-navy-600 text-white ml-1.5 px-1.5 py-0 text-[10px] align-middle">최저</span>}
            {attrs && <span className="ml-1.5 font-normal text-xs text-muted">{attrs}</span>}
          </span>
          <span className="block mt-1"><Badges it={it} /></span>
        </span>
        <span className="block mt-1.5 md:mt-0 text-xs text-navy-700 break-all md:pt-0.5">{it.spec}<span className="text-muted"> / {it.unit}</span></span>
        <span className="flex md:block items-baseline justify-between mt-2 md:mt-0 md:text-right tabular-nums">
          <span className="md:hidden text-[11px] text-muted">단가</span>
          <span>
            <span className="font-semibold text-navy-900">{won(it[pp])}</span>
            {it.tax_estimated && pp === 'unit_price_tax' && <span className="text-muted text-xs"> ≈</span>}
            <span className="hidden md:block"><Change c={it.change} /></span>
          </span>
        </span>
        <span className="block mt-1 md:mt-0 md:text-right tabular-nums">
          {kg != null ? (
            <>
              <span className="flex md:block items-baseline justify-between">
                <span className="md:hidden text-[11px] text-muted">{it.per_unit_label}</span>
                <span className="font-bold text-navy-900">{won(kg)}<span className="text-[10.5px] font-normal text-muted"> {it.per_unit_label === 'kg당' ? '/kg' : '/L'}</span></span>
              </span>
              {it.per_unit_label === 'kg당' && <KgBar v={kg} domain={domain} color={SUP[it.supplier]?.color} />}
            </>
          ) : <span className="text-muted text-sm">—</span>}
        </span>
      </button>
    </li>
  )
}

// ─────────────────────────── 상세 패널 ───────────────────────────
function ItemPanel({ ref_, vat, dist, onClose }) {
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
  const s = SUP[ref_.supplier]
  // 이 검색 결과 안에서 kg당 가격이 어디쯤인지 (dist 는 화면 비교와 같은 부가세 기준)
  let rank = null
  if (it && it[pk] != null && it.per_unit_label === 'kg당' && dist?.length > 4) {
    rank = Math.round((dist.filter((d) => d.v < it[pk]).length / dist.length) * 100)
  }
  const { name, attrs } = splitName(it?.item_nm || '')

  return (
    <div className="fixed inset-0 z-40 no-print">
      <div className="absolute inset-0 bg-navy-950/35" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full max-w-[440px] bg-white shadow-lift overflow-y-auto">
        <div className="h-1.5" style={{ background: s?.color }} />
        <div className="sticky top-0 z-10 bg-white border-b border-navy-100 px-5 py-3 flex items-center justify-between">
          <SupTag sup={ref_.supplier} />
          <button onClick={onClose} className="w-8 h-8 inline-flex items-center justify-center rounded-full text-muted hover:bg-navy-50" aria-label="닫기"><Icon name="x" /></button>
        </div>
        {err && <p className="m-5 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}
        {!it && !err && <div className="p-5 space-y-3 animate-pulse"><div className="h-6 bg-navy-50 rounded" /><div className="h-24 bg-navy-50 rounded-2xl" /><div className="h-40 bg-navy-50 rounded-2xl" /></div>}
        {it && (
          <div className="px-5 py-5">
            <h2 className="text-xl font-extrabold text-navy-900 leading-snug">{name}</h2>
            {attrs && <p className="mt-0.5 text-sm text-navy-700">{attrs}</p>}
            {it.category && <p className="mt-1 text-xs text-muted">{it.category}{it.category_auto && <span className="ml-1.5 badge px-1.5 py-0 text-[10px] bg-slate-100 text-slate-500" title="사조는 분류 정보를 주지 않아 품목명으로 추정했어요">자동 분류</span>}</p>}
            <div className="mt-2.5"><Badges it={it} /></div>

            <div className="mt-5 grid grid-cols-2 gap-2.5">
              <div className="rounded-2xl px-4 py-3.5" style={{ background: s?.tint }}>
                <p className="text-[11px] text-navy-700">단가 {vat ? '· 부가세 포함' : '· 부가세 별도'}</p>
                <p className="mt-1 text-[22px] leading-tight font-extrabold text-navy-900 tabular-nums">{won(it[pp])}{it.tax_estimated && vat ? <span className="text-xs text-muted"> ≈</span> : ''}</p>
                <p className="text-[11px] text-muted">{it.unit} 1개 기준</p>
              </div>
              <div className="rounded-2xl bg-navy-50/70 px-4 py-3.5">
                <p className="text-[11px] text-navy-700">{it.per_unit_label} 환산</p>
                <p className="mt-1 text-[22px] leading-tight font-extrabold text-navy-900 tabular-nums">{won(it[pk])}</p>
                <p className="text-[11px] text-muted">{it.pack_g ? `포장 ${it.pack_g >= 1000 ? `${+(it.pack_g / 1000).toFixed(2)}kg` : `${it.pack_g}g`} 기준` : '규격에서 중량을 읽지 못함'}</p>
              </div>
            </div>

            {rank != null && (
              <div className="mt-3 rounded-2xl border border-navy-100 px-4 py-3">
                <div className="flex justify-between text-[11px]"><span className="text-muted">이 검색 결과 안에서 kg당 가격 위치</span>
                  <b className="text-navy-900">{rank <= 50 ? `저렴한 쪽 상위 ${Math.max(rank, 1)}%` : `비싼 쪽 상위 ${Math.max(100 - rank, 1)}%`}</b></div>
                <div className="relative mt-2.5 h-2 rounded-full bg-navy-50">
                  <span className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 rounded-full ring-2 ring-white shadow"
                    style={{ left: `${Math.min(Math.max(rank, 2), 98)}%`, background: s?.color }} />
                </div>
                <div className="mt-1 flex justify-between text-[10px] text-muted"><span>저렴</span><span>비쌈</span></div>
              </div>
            )}

            <ItemTrend data={data} it={it} color={s?.color} />

            <dl className="mt-6 text-sm divide-y divide-navy-100 border-y border-navy-100">
              {[
                ['규격', it.spec], ['단위', it.unit], ['원산지', it.origin], ['과세', it.tax_type],
                ['최소 발주', it.min_order_day], ['단품코드', it.item_cd], ['단가표 기준일', fmtDay(it.last_seen)],
              ].filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="flex gap-3 py-2"><dt className="w-24 shrink-0 text-muted">{k}</dt><dd className="text-navy-900 break-all">{v}</dd></div>
              ))}
            </dl>
            {it.stale && <p className="mt-3 text-xs rounded-xl bg-slate-50 text-slate-600 px-3 py-2">최근 단가표에 없는 품목입니다. 단종됐거나 발주가 막혔을 수 있어요.</p>}
          </div>
        )}
      </aside>
    </div>
  )
}

// 단가는 바뀐 날까지 유지되므로 계단형 선. 마우스를 올리면 그 시점 단가를 보여준다.
function PriceChart({ history, current, today, color = '#1151b8' }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)
  const pts = useMemo(() => {
    const out = []
    for (const h of history || []) if (h.unit_price != null) out.push({ d: h.changed_on, v: +h.unit_price })
    if (out.length && today && today > out[out.length - 1].d) out.push({ d: today, v: current ?? out[out.length - 1].v, tail: true })
    return out
  }, [history, current, today])
  const changes = (history || []).filter((h) => h.change_type === 'changed')
  const flat = pts.length < 2 || !changes.length

  const W = Math.max(width, 260), H = 160, L = 44, R = 10, T = 14, B = 24
  let body = null
  if (!flat) {
    const t0 = new Date(pts[0].d).getTime(), t1 = Math.max(new Date(pts[pts.length - 1].d).getTime(), t0 + 1)
    const vs = pts.map((p) => p.v)
    let lo = Math.min(...vs), hi = Math.max(...vs)
    const pad = (hi - lo) * 0.3 || hi * 0.08 || 1
    lo = Math.max(0, lo - pad); hi += pad
    const x = (d) => L + ((new Date(d).getTime() - t0) / (t1 - t0)) * (W - L - R)
    const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
    let line = `M${x(pts[0].d)},${y(pts[0].v)}`
    for (let i = 1; i < pts.length; i++) line += ` H${x(pts[i].d)} V${y(pts[i].v)}`
    const area = `${line} V${H - B} H${x(pts[0].d)} Z`
    const yt = [lo + (hi - lo) * 0.2, lo + (hi - lo) * 0.8]
    const onMove = (e) => {
      const px = e.clientX - e.currentTarget.getBoundingClientRect().left
      let i = 0
      for (let k = 0; k < pts.length; k++) if (x(pts[k].d) <= px) i = k
      setHover({ i, px: Math.min(Math.max(px, L), W - R) })
    }
    const hp = hover && pts[hover.i]
    const gid = `g${color.replace('#', '')}`
    body = (
      <div className="relative">
        <svg width={W} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="단가 추이 그래프">
          <defs><linearGradient id={gid} x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor={color} stopOpacity="0.16" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
          {yt.map((v) => (
            <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#eef3fb" />
              <text x={L - 6} y={y(v) + 3.5} fontSize="10" fill="#64748b" textAnchor="end">{short(Math.round(v))}</text></g>
          ))}
          <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="#d7e3f6" />
          <path d={area} fill={`url(#${gid})`} />
          <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" />
          {pts.filter((p) => !p.tail).map((p) => <circle key={p.d} cx={x(p.d)} cy={y(p.v)} r="4" fill={color} stroke="#fff" strokeWidth="2" />)}
          <text x={L} y={H - 7} fontSize="10" fill="#64748b">{fmtDay(pts[0].d)}</text>
          <text x={W - R} y={H - 7} fontSize="10" fill="#64748b" textAnchor="end">{fmtDay(pts[pts.length - 1].d)}</text>
          {hp && <><line x1={hover.px} x2={hover.px} y1={T - 4} y2={H - B} stroke="#7fa1de" strokeDasharray="3 3" />
            <circle cx={x(hp.d)} cy={y(hp.v)} r="5.5" fill="#fff" stroke={color} strokeWidth="2.5" /></>}
        </svg>
        {hp && (
          <div className="absolute top-0 pointer-events-none rounded-lg bg-navy-900 text-white text-[11px] px-2.5 py-1.5 shadow-lift tabular-nums"
            style={{ left: hover.px, transform: `translateX(${hover.px > W / 2 ? '-108%' : '8%'})` }}>
            <p className="text-white/65">{fmtDay(hp.d)}{hp.tail ? ' · 현재' : ''}</p><p className="font-semibold">{won(hp.v)}</p>
          </div>
        )}
      </div>
    )
  }

  return (
    <div ref={ref} className="mt-2">
      {flat ? (
        <div className="rounded-2xl bg-navy-50/50 px-4 py-5 text-sm text-muted leading-6">
          {pts.length ? <>{fmtDay(pts[0].d)} 등록 이후 <b className="text-navy-900">단가 변동 없음</b> · {won(pts[0].v)}</> : '아직 기록이 없습니다.'}
          <br /><span className="text-xs">단가가 바뀌면 여기에 추이가 쌓입니다.</span>
        </div>
      ) : (
        <>
          {width > 0 && body}
          <ul className="mt-2 space-y-1 text-xs">
            {[...changes].reverse().slice(0, 6).map((h) => {
              const p0 = +h.prev_price, p1 = +h.unit_price
              const pct = p0 ? Math.round(((p1 - p0) / p0) * 1000) / 10 : 0
              return (
                <li key={h.changed_on} className="flex items-center gap-2 tabular-nums">
                  <span className="w-16 text-muted">{fmtDay(h.changed_on)}</span>
                  <span className="text-navy-700">{won(p0)} → <b className="text-navy-900">{won(p1)}</b></span>
                  <Change c={{ pct, prev: p0, now: p1, on: h.changed_on }} />
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

// ─────────────────────────── 시세 동향 (월별 · 계절) ───────────────────────────
const LCLS = ['농산품', '축산품', '수산품', '공산품']
const MONTHS = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월']
const ym = (s) => `${+s.slice(2, 4)}.${+s.slice(5, 7)}`
const pctTxt = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`)

function Pct({ v, label }) {
  if (v == null) return <span className="text-muted">{label} —</span>
  const up = v > 0.05, down = v < -0.05
  return (
    <span className="tabular-nums" style={{ color: up ? UP : down ? DOWN : '#64748b' }}>
      {label} <b>{up ? '▲' : down ? '▼' : ''}{Math.abs(v).toFixed(1)}%</b>
    </span>
  )
}

function Spark({ series, w = 96, h = 26 }) {
  const all = series.flatMap((s) => s.values).filter((v) => v != null)
  if (all.length < 2) return <svg width={w} height={h} />
  const lo = Math.min(...all), hi = Math.max(...all), n = Math.max(...series.map((s) => s.values.length))
  const x = (i) => 2 + (i / Math.max(n - 1, 1)) * (w - 4)
  const y = (v) => h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6)
  return (
    <svg width={w} height={h} aria-hidden="true">
      {series.map((s) => (
        <path key={s.key} fill="none" stroke={s.color} strokeWidth="1.6" strokeLinejoin="round"
          d={s.values.map((v, i) => (v == null ? '' : `${i ? 'L' : 'M'}${x(i)},${y(v)}`)).join(' ')} />
      ))}
    </svg>
  )
}

// 같은 값축(지수) 위에 공급사별 선. 마우스 위치의 달을 세로선과 함께 보여준다.
function IndexChart({ series }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)
  const sups = SUP_KEYS.filter((s) => series?.[s]?.length)
  const months = [...new Set(sups.flatMap((s) => series[s].map((p) => p.month)))].sort()
  const W = Math.max(width, 300), H = 240, L = 40, R = 56, T = 14, B = 26
  const vals = sups.flatMap((s) => series[s].map((p) => p.idx)).filter((v) => v != null)
  let lo = Math.min(...vals, 100), hi = Math.max(...vals, 100)
  const pad = Math.max((hi - lo) * 0.15, 2); lo -= pad; hi += pad
  const x = (m) => L + (months.indexOf(m) / Math.max(months.length - 1, 1)) * (W - L - R)
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
  const step = (hi - lo) > 30 ? 10 : (hi - lo) > 12 ? 5 : 2
  const yt = []; for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) yt.push(v)
  const xt = months.filter((m, i) => months.length <= 13 || m.endsWith('-01') || i === months.length - 1)
  const onMove = (e) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left
    let best = null, bd = 1e9
    months.forEach((m) => { const d = Math.abs(x(m) - px); if (d < bd) { bd = d; best = m } })
    setHover(best)
  }
  // 오른쪽 끝 이름표가 겹치지 않게 살짝 벌린다
  const ends = sups.map((s) => { const p = series[s][series[s].length - 1]; return { s, v: p.idx, y: y(p.idx) } }).sort((a, b) => a.y - b.y)
  for (let i = 1; i < ends.length; i++) if (ends[i].y - ends[i - 1].y < 14) ends[i].y = ends[i - 1].y + 14

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={W} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="공급사별 월별 가격 지수">
          {yt.map((v) => (
            <g key={v}>
              <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v === 100 ? '#b0c6ec' : '#eef3fb'} strokeDasharray={v === 100 ? '4 3' : undefined} />
              <text x={L - 6} y={y(v) + 3.5} fontSize="10" fill="#64748b" textAnchor="end">{v}</text>
            </g>
          ))}
          {xt.map((m) => <text key={m} x={x(m)} y={H - 7} fontSize="10" fill="#64748b" textAnchor="middle">{m.endsWith('-01') ? `${m.slice(2, 4)}년 1월` : ym(m)}</text>)}
          {hover && <line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="#7fa1de" strokeDasharray="3 3" />}
          {sups.map((s) => {
            const pts = series[s].filter((p) => p.idx != null)
            return (
              <g key={s}>
                <path fill="none" stroke={SUP[s].color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
                  d={pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.month)},${y(p.idx)}`).join(' ')} />
                {hover && pts.filter((p) => p.month === hover).map((p) => (
                  <circle key={p.month} cx={x(p.month)} cy={y(p.idx)} r="4.5" fill={SUP[s].color} stroke="#fff" strokeWidth="2" />
                ))}
              </g>
            )
          })}
          {ends.map((e) => (
            <text key={e.s} x={W - R + 6} y={e.y + 4} fontSize="11" fontWeight="700" fill="#07204d">{SUP[e.s].short} {Math.round(e.v)}</text>
          ))}
        </svg>
      )}
      {hover && (
        <div className="absolute top-1 pointer-events-none z-10 rounded-xl bg-navy-900 text-white px-3 py-2 shadow-lift text-[11.5px] tabular-nums"
          style={{ left: x(hover), transform: `translateX(${x(hover) > W / 2 ? '-108%' : '8%'})` }}>
          <p className="text-white/65 mb-1">{hover.slice(0, 4)}년 {+hover.slice(5, 7)}월</p>
          {sups.map((s) => {
            const p = series[s].find((q) => q.month === hover)
            return p ? (
              <p key={s} className="flex items-center gap-1.5 whitespace-nowrap">
                <span className="w-2 h-2 rounded-full" style={{ background: SUP[s].color }} />{SUP[s].short}
                <b className="ml-1">{p.idx?.toFixed(1)}</b>
                <span className="text-white/65">전월 {pctTxt(p.mom_pct)}</span>
              </p>
            ) : null
          })}
        </div>
      )}
    </div>
  )
}

// 계절 띠: 그해 평균 대비 달별 % (파랑 = 싼 달, 빨강 = 비싼 달, 회색 = 평균 근처)
function seasonColor(v, max) {
  if (v == null) return { bg: '#f8fafc', fg: '#cbd5e1' }
  const t = Math.min(Math.abs(v) / Math.max(max, 4), 1)
  const mix = (a, b) => Math.round(a + (b - a) * t)
  const [r, g, b] = v >= 0 ? [mix(241, 220), mix(243, 38), mix(246, 38)] : [mix(241, 17), mix(243, 81), mix(246, 184)]
  return { bg: `rgb(${r},${g},${b})`, fg: t > 0.55 ? '#fff' : '#0f172a' }
}

function SeasonStrip({ rows, compact }) {
  const valid = rows.filter((r) => r.data)
  if (!valid.length) return null
  const max = Math.max(...valid.flatMap((r) => r.data.pct.filter((v) => v != null).map(Math.abs)), 4)
  const now = new Date().getMonth()
  return (
    <div>
      <div className={`grid gap-1 ${compact ? 'grid-cols-[repeat(12,minmax(0,1fr))]' : 'grid-cols-[44px_repeat(12,minmax(0,1fr))]'} text-[10px] text-muted mb-1`}>
        {!compact && <span />}
        {MONTHS.map((m, i) => (
          <span key={m} className={`text-center whitespace-nowrap ${i === now ? 'font-bold text-navy-900' : ''}`}>
            <span className="sm:hidden">{i + 1}</span><span className="hidden sm:inline">{m}</span>
          </span>
        ))}
      </div>
      {valid.map((r) => (
        <div key={r.key} className={`grid gap-1 mb-1 ${compact ? 'grid-cols-[repeat(12,minmax(0,1fr))]' : 'grid-cols-[44px_repeat(12,minmax(0,1fr))]'}`}>
          {!compact && <span className="text-[11px] font-semibold text-navy-900 self-center"><SupTag sup={r.key} short /></span>}
          {r.data.pct.map((v, i) => {
            const c = seasonColor(v, max)
            return (
              <span key={i} title={`${MONTHS[i]}: 그해 평균 대비 ${pctTxt(v)}`}
                className={`h-8 rounded-md flex items-center justify-center text-[9.5px] sm:text-[10px] font-semibold tabular-nums tracking-tighter sm:tracking-normal ${i === now ? 'ring-2 ring-navy-900 ring-offset-1' : ''}`}
                style={{ background: c.bg, color: c.fg }}>
                {v == null ? '·' : `${v > 0 ? '+' : ''}${Math.round(v)}`}
              </span>
            )
          })}
        </div>
      ))}
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-[10.5px] text-muted whitespace-nowrap">
        <span className="inline-flex items-center gap-1.5">
          <span className="w-3 h-3 rounded" style={{ background: seasonColor(-max, max).bg }} />싼 달
          <span className="w-3 h-3 rounded ml-2" style={{ background: '#f1f3f6' }} />평균
          <span className="w-3 h-3 rounded ml-2" style={{ background: seasonColor(max, max).bg }} />비싼 달
        </span>
        <span>숫자 = 그해 평균 대비 % · {valid[0].data.years.join('·')}년 기준</span>
      </div>
    </div>
  )
}

function TrendSection() {
  const [base, setBase] = useState(null)
  const [lcls, setLcls] = useState('농산품')
  const [mcls, setMcls] = useState('전체')
  const [data, setData] = useState(null)
  useEffect(() => { api.get('/prices/trends').then((r) => setBase(r.data)).catch((e) => setBase({ months: 0, error: errMsg(e, '서버에서 시세 정보를 불러오지 못했습니다.') })) }, [])
  useEffect(() => {
    if (!base?.months) return
    setData(null)
    api.get('/prices/trends', { params: { lcls, mcls } }).then((r) => setData(r.data)).catch(() => {})
  }, [base?.months, lcls, mcls])

  const subs = (base?.groups || []).filter((g) => g.lcls === lcls).slice(0, 8)
  const enough = (base?.months || 0) >= 2

  return (
    <section className="surface p-5 mt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-bold text-navy-900">시세 동향 <span className="text-xs font-normal text-muted ml-1">월별 · 계절별</span></p>
          <p className="text-[11px] text-muted mt-0.5">같은 품목들의 가격 변화를 이어 붙인 지수 · 처음 달 = 100{base?.first && ` · ${ym(base.first)} ~ ${ym(base.last)}`}</p>
        </div>
      </div>

      {!base ? (
        <div className="mt-4 h-40 rounded-xl bg-navy-50/60 animate-pulse" />
      ) : base.error ? (
        <div className="mt-4 rounded-xl bg-red-50 text-red-700 px-5 py-4 text-sm leading-6">
          시세 정보를 불러오지 못했습니다 ({base.error}). 서버가 새 버전으로 배포 중이면 잠시 뒤 새로고침해 주세요.
        </div>
      ) : !enough ? (
        <div className="mt-4 rounded-xl bg-navy-50/50 px-5 py-6 text-sm text-muted leading-6">
          <p className="font-semibold text-navy-900">월별 추이는 두 달 이상 쌓이면 그려집니다 (현재 {base.months || 0}개월)</p>
          <p className="mt-1">매일 아침 수집하면서 자동으로 쌓이고, 계절 패턴은 한 해(10개월 이상)가 모이면 나타나요.
            지난 기간 단가표를 채우면 바로 볼 수 있습니다 — <code className="text-[12px] bg-white px-1.5 py-0.5 rounded">backfill.bat hgreenfood 202411 202610</code></p>
        </div>
      ) : (
        <>
          {/* 대분류 요약 카드 (누르면 아래 그래프가 바뀜) */}
          <div className="mt-4 grid grid-cols-2 lg:grid-cols-4 gap-2.5">
            {LCLS.map((l) => {
              const items = base.overview.filter((o) => o.lcls === l)
              if (!items.length) return null
              const on = lcls === l
              return (
                <button key={l} onClick={() => { setLcls(l); setMcls('전체') }}
                  className={`text-left rounded-2xl border px-3.5 py-3 transition ${on ? 'border-navy-600 bg-navy-50/50 ring-1 ring-navy-600' : 'border-navy-100 hover:border-navy-300'}`}>
                  <div className="flex items-center justify-between">
                    <span className="text-[13px] font-bold text-navy-900 whitespace-nowrap">{l}</span>
                    <span className="hidden sm:block"><Spark series={items.map((o) => ({ key: o.supplier, color: SUP[o.supplier].color, values: o.spark }))} /></span>
                  </div>
                  <div className="mt-1.5 space-y-0.5 text-[11px]">
                    {items.map((o) => (
                      <p key={o.supplier} className="flex items-center gap-1.5">
                        <SupTag sup={o.supplier} short className="w-11" />
                        <Pct v={o.yoy_pct ?? o.mom_pct} label={o.yoy_pct != null ? '전년' : '전월'} />
                      </p>
                    ))}
                  </div>
                </button>
              )
            })}
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-1.5">
            {['전체', ...subs.map((g) => g.mcls)].map((m) => (
              <button key={m} onClick={() => setMcls(m)}
                className={`px-3 py-1 rounded-full text-xs font-semibold border transition ${mcls === m ? 'bg-navy-900 text-white border-navy-900' : 'bg-white text-navy-700 border-navy-100 hover:border-navy-300'}`}>
                {m === '전체' ? `${lcls} 전체` : m}
              </button>
            ))}
          </div>

          <div className="mt-3 grid gap-5 lg:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="flex items-center gap-4 text-[11px] text-muted mb-1">
                {SUP_KEYS.filter((s) => data?.series?.[s]).map((s) => (
                  <span key={s} className="inline-flex items-center gap-1.5"><span className="w-4 h-[3px] rounded" style={{ background: SUP[s].color }} />{SUP[s].label}</span>
                ))}
                <span className="inline-flex items-center gap-1.5"><span className="w-4 border-t border-dashed border-navy-300" />기준 100</span>
              </div>
              {data ? (Object.keys(data.series || {}).length ? <IndexChart series={data.series} /> : <p className="py-16 text-center text-sm text-muted">이 분류의 데이터가 없습니다.</p>)
                : <div className="h-60 rounded-xl bg-navy-50/50 animate-pulse" />}
            </div>
            <div>
              <p className="text-[12px] font-bold text-navy-900 mb-2">계절 패턴 <span className="font-normal text-muted">어느 달에 싸고 비싼가</span></p>
              {data && SUP_KEYS.some((s) => data.seasonal?.[s]) ? (
                <SeasonStrip rows={SUP_KEYS.map((s) => ({ key: s, data: data.seasonal?.[s] }))} />
              ) : (
                <div className="rounded-xl bg-navy-50/50 px-4 py-6 text-[12.5px] text-muted leading-6">
                  한 해에 10개월 이상 쌓이면 달별로 싼 때와 비싼 때를 보여줍니다.
                </div>
              )}
              {data && <LatestNote series={data.series} />}
              <p className="mt-3 text-[10.5px] leading-4 text-muted">
                계약·마진 변경처럼 거의 모든 품목이 같은 비율로 한꺼번에 바뀐 시점은 시세 변동이 아니므로 자동 보정했어요
                (예: 사조 2026년 10→11월 전 품목 ×1.40).
              </p>
            </div>
          </div>
        </>
      )}
    </section>
  )
}

function LatestNote({ series }) {
  const lines = SUP_KEYS.filter((s) => series?.[s]?.length).map((s) => {
    const p = series[s][series[s].length - 1]
    return { s, p }
  })
  if (!lines.length) return null
  return (
    <div className="mt-4 rounded-xl border border-navy-100 divide-y divide-navy-100 text-[12px]">
      {lines.map(({ s, p }) => (
        <div key={s} className="px-3 py-2 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          <SupTag sup={s} short className="w-11" />
          <span className="text-muted">{ym(p.month)}</span>
          <Pct v={p.mom_pct} label="전월" />
          <Pct v={p.yoy_pct} label="전년 같은 달" />
          {p.up_share != null && <span className="text-muted">오른 품목 {Math.round(p.up_share * 100)}% · 내린 품목 {Math.round(p.down_share * 100)}%</span>}
        </div>
      ))}
    </div>
  )
}

// 상세 패널: 품목 월평균 (선 = 월평균, 옅은 띠 = 그 달 최저~최고)
function MonthlyChart({ rows, color }) {
  const [ref, width] = useWidth()
  const [hover, setHover] = useState(null)
  const W = Math.max(width, 260), H = 170, L = 44, R = 10, T = 12, B = 24
  const vals = rows.flatMap((r) => [r.min, r.max, r.avg]).filter((v) => v != null)
  let lo = Math.min(...vals), hi = Math.max(...vals)
  const pad = (hi - lo) * 0.25 || hi * 0.08 || 1; lo = Math.max(0, lo - pad); hi += pad
  const n = rows.length
  const x = (i) => L + (n === 1 ? 0.5 : i / (n - 1)) * (W - L - R)
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B)
  const yt = [lo + (hi - lo) * 0.2, lo + (hi - lo) * 0.8]
  const line = rows.map((r, i) => `${i ? 'L' : 'M'}${x(i)},${y(r.avg)}`).join(' ')
  const band = rows.map((r, i) => `${i ? 'L' : 'M'}${x(i)},${y(r.max)}`).join(' ') + ' ' +
    [...rows].reverse().map((r, k) => `L${x(n - 1 - k)},${y(r.min)}`).join(' ') + ' Z'
  const onMove = (e) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left
    setHover(Math.min(Math.max(Math.round(((px - L) / (W - L - R)) * (n - 1)), 0), n - 1))
  }
  const hr = hover != null ? rows[hover] : null
  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={W} height={H} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label="월평균 단가">
          {yt.map((v) => (
            <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#eef3fb" />
              <text x={L - 6} y={y(v) + 3.5} fontSize="10" fill="#64748b" textAnchor="end">{short(Math.round(v))}</text></g>
          ))}
          <line x1={L} x2={W - R} y1={H - B} y2={H - B} stroke="#d7e3f6" />
          <path d={band} fill={color} fillOpacity="0.12" />
          <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
          {hr && <><line x1={x(hover)} x2={x(hover)} y1={T} y2={H - B} stroke="#7fa1de" strokeDasharray="3 3" />
            <circle cx={x(hover)} cy={y(hr.avg)} r="5" fill="#fff" stroke={color} strokeWidth="2.5" /></>}
          {rows.map((r, i) => (n <= 12 || (r.month.endsWith('-01') && i > 1 && i < n - 2) || i === n - 1 || i === 0) && (
            <text key={r.month} x={x(i)} y={H - 7} fontSize="10" fill="#64748b"
              textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}>
              {r.month.endsWith('-01') && n > 12 && i !== 0 && i !== n - 1 ? `${r.month.slice(2, 4)}년` : ym(r.month)}
            </text>
          ))}
        </svg>
      )}
      {hr && (
        <div className="absolute top-0 pointer-events-none rounded-lg bg-navy-900 text-white text-[11px] px-2.5 py-1.5 shadow-lift tabular-nums"
          style={{ left: x(hover), transform: `translateX(${x(hover) > W / 2 ? '-108%' : '8%'})` }}>
          <p className="text-white/65">{hr.month.slice(0, 4)}년 {+hr.month.slice(5, 7)}월 · 단가표 {hr.days}회</p>
          <p className="font-semibold">평균 {won(hr.avg)}</p>
          {hr.min !== hr.max && <p className="text-white/75">{won(hr.min)} ~ {won(hr.max)}</p>}
          <p className="text-white/75">전월 {pctTxt(hr.mom_pct)} · 전년 {pctTxt(hr.yoy_pct)}</p>
        </div>
      )}
      <p className="mt-1 text-[10.5px] text-muted">선 = 월평균 · 옅은 띠 = 그 달 최저~최고</p>
    </div>
  )
}

function ItemTrend({ data, it, color }) {
  const monthly = data.monthly || []
  const [tab, setTab] = useState(monthly.length >= 2 ? 'month' : 'daily')
  const last = monthly[monthly.length - 1]
  return (
    <div className="mt-6">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-bold text-navy-900">단가 추이 <span className="text-xs font-normal text-muted">공급가 · 부가세 별도</span></p>
        <Seg value={tab} onChange={setTab} options={[['month', '월별'], ['daily', '변동 이력']]} />
      </div>
      {tab === 'month' ? (
        monthly.length >= 2 ? (
          <>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11.5px]">
              <span className="text-muted">{ym(last.month)} 평균 <b className="text-navy-900">{won(last.avg)}</b></span>
              <Pct v={last.mom_pct} label="전월" />
              <Pct v={last.yoy_pct} label="전년 같은 달" />
            </div>
            <div className="mt-2"><MonthlyChart rows={monthly} color={color} /></div>
            {data.seasonal && Math.max(...data.seasonal.pct.filter((v) => v != null).map(Math.abs)) < 1 ? (
              <p className="mt-3 text-[11.5px] text-muted">계절 패턴: 달마다 가격 변동이 거의 없는 품목이에요 (±1% 미만).</p>
            ) : data.seasonal ? (
              <div className="mt-4">
                <p className="text-[12px] font-bold text-navy-900 mb-2">계절 패턴</p>
                <SeasonStrip rows={[{ key: it.supplier, data: data.seasonal }]} compact />
              </div>
            ) : <p className="mt-3 text-[11.5px] text-muted">한 해에 10개월 이상 쌓이면 달별 계절 패턴이 나타납니다.</p>}
          </>
        ) : (
          <div className="mt-2 rounded-2xl bg-navy-50/50 px-4 py-5 text-sm text-muted leading-6">
            월별 추이는 두 달 이상 쌓이면 그려집니다{monthly.length ? ` (현재 ${monthly.length}개월)` : ''}.
          </div>
        )
      ) : (
        <PriceChart history={data.history} current={it.unit_price} today={it.last_seen} color={color} />
      )}
    </div>
  )
}

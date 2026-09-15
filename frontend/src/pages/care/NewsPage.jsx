import { useEffect, useState } from 'react'
import api from '../../lib/api'
import CareLayout, { Empty } from '../../components/care/CareLayout'
import { errMsg } from '../../components/care/CareUI'
import useAuthStore from '../../lib/authStore'

const CATS = ['노인 전반', '돌봄·요양', '고령자 식품·영양', '정책·제도']

const CAT_STYLE = {
  '노인 전반': 'bg-navy-50 text-navy-700 border-navy-200',
  '돌봄·요양': 'bg-teal-50 text-teal-700 border-teal-200',
  '고령자 식품·영양': 'bg-amber-50 text-amber-700 border-amber-200',
  '정책·제도': 'bg-violet-50 text-violet-700 border-violet-200',
}

const WD = ['일', '월', '화', '수', '목', '금', '토']

function fmtDay(d) {
  if (!d) return ''
  const [y, m, day] = d.split('-')
  return `${m}.${day} (${WD[new Date(+y, +m - 1, +day).getDay()]})`
}

function fmtTime(iso) {
  if (!iso) return ''
  const t = new Date(iso)
  return Number.isNaN(t.getTime())
    ? ''
    : `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`
}

export default function NewsPage() {
  const { user, isAdmin } = useAuthStore()
  const canCollect = isAdmin || user?.staff_role === 'manager'
  const [dates, setDates] = useState([])
  const [date, setDate] = useState(null)
  const [data, setData] = useState(null)
  const [cat, setCat] = useState('전체')
  const [q, setQ] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = (d) => {
    setData(null)
    api.get('/news/daily', { params: d ? { date: d } : {} })
      .then((r) => { setData(r.data); setDate(r.data.date) })
      .catch((e) => setErr(errMsg(e)))
  }

  useEffect(() => {
    api.get('/news/dates').then((r) => setDates(r.data.dates || [])).catch(() => {})
    load(null)
  }, [])

  // 검색 23회 + 요약 1회라 몇 분 걸린다. axios 기본 타임아웃(15초)으로는 항상 끊긴다.
  const COLLECT_TIMEOUT = 10 * 60 * 1000

  const collectError = (e) => {
    if (e?.code === 'ECONNABORTED') {
      return '시간이 초과됐습니다. 서버에서는 계속 진행 중일 수 있으니 잠시 후 새로고침해 보세요.'
    }
    if (!e?.response) {
      return '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.'
    }
    return errMsg(e, `수집에 실패했습니다. (HTTP ${e.response.status})`)
  }

  const runCollect = () => {
    setBusy(true); setErr('')
    api.post('/news/collect', null, { timeout: COLLECT_TIMEOUT })
      .then(() => api.get('/news/dates').then((r) => setDates(r.data.dates || [])))
      .then(() => load(null))
      .catch((e) => setErr(collectError(e)))
      .finally(() => setBusy(false))
  }

  const term = q.trim().toLowerCase()
  const rows = (data?.articles || []).filter((a) => {
    if (cat !== '전체' && a.category !== cat) return false
    if (!term) return true
    return `${a.title} ${a.summary || ''} ${a.press || ''}`.toLowerCase().includes(term)
  })

  return (
    <CareLayout
      title="동향"
      subtitle="노인·돌봄·고령친화식품·정책 뉴스를 매일 아침 모아 요약합니다."
      actions={canCollect && (
        <button onClick={runCollect} disabled={busy} className="btn-secondary disabled:opacity-50">
          {busy ? '수집 중… (3~5분)' : '지금 수집'}
        </button>
      )}
    >
      {err && <p className="mb-4 text-sm rounded-xl bg-red-50 text-red-700 px-4 py-3">{err}</p>}

      {dates.length > 0 && (
        <div className="flex gap-2 overflow-x-auto pb-3 mb-5 border-b border-navy-100">
          {dates.map((d) => {
            const on = d.brief_date === date
            return (
              <button key={d.brief_date} onClick={() => { setCat('전체'); setQ(''); load(d.brief_date) }}
                className={`shrink-0 text-left rounded-xl px-3 py-2 transition ${on ? 'bg-navy-900 text-white' : 'text-muted hover:bg-navy-50'}`}>
                <span className="block text-[13px] font-semibold tabular-nums">{fmtDay(d.brief_date)}</span>
                <span className={`block text-[11px] ${on ? 'text-white/60' : 'text-muted'}`}>{d.article_count}건</span>
              </button>
            )
          })}
        </div>
      )}

      {!data ? (
        <div className="surface p-12 text-center text-muted">불러오는 중…</div>
      ) : !data.date ? (
        <Empty icon="record" title="아직 브리핑이 없습니다"
          desc={canCollect
            ? "'지금 수집'을 누르면 오늘 기사를 모아 요약합니다. 이후에는 매일 아침 자동으로 갱신됩니다."
            : '매일 아침 자동으로 갱신됩니다. 잠시 후 다시 확인해 주세요.'} />
      ) : (
        <>
          {data.briefing?.length > 0 && (
            <section className="rounded-2xl bg-navy-50/70 border-l-[3px] border-navy-600 px-6 py-5 mb-6">
              <p className="eyebrow text-navy-600 mb-3">{fmtDay(data.date)} 핵심</p>
              <ol className="space-y-2.5">
                {data.briefing.map((line, i) => (
                  <li key={i} className="flex gap-3 text-[15px] leading-relaxed text-navy-900">
                    <span className="shrink-0 text-xs font-semibold text-navy-500 tabular-nums pt-1">{i + 1}</span>
                    <span>{line}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}

          <div className="flex flex-wrap items-center gap-2 mb-4">
            {['전체', ...CATS].map((c) => {
              const n = data.counts?.[c] ?? 0
              if (c !== '전체' && !n) return null
              return (
                <button key={c} onClick={() => setCat(c)}
                  className={`px-3 py-1.5 rounded-full text-xs font-semibold border transition ${
                    cat === c ? 'bg-navy-900 text-white border-navy-900' : 'bg-white border-navy-100 text-muted hover:border-navy-200'}`}>
                  {c} <span className="tabular-nums opacity-70">{n}</span>
                </button>
              )
            })}
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·요약 검색"
              className="form-input ml-auto w-full sm:w-52 py-1.5 text-sm" />
          </div>

          {rows.length === 0 ? (
            <div className="surface p-12 text-center text-muted">조건에 맞는 기사가 없습니다.</div>
          ) : (
            <div className="divide-y divide-navy-100 border-t border-navy-100">
              {rows.map((a) => (
                <article key={a.id} className="py-5 sm:grid sm:grid-cols-[76px_1fr] sm:gap-5">
                  <div className="flex sm:flex-col items-center sm:items-start gap-2 sm:gap-1 mb-2 sm:mb-0">
                    <span className="text-xs text-muted tabular-nums">{fmtTime(a.published_at)}</span>
                    <span className="text-xs text-navy-700 truncate">{a.press}</span>
                  </div>
                  <div>
                    <h3 className={`font-semibold leading-snug ${a.is_key ? 'text-[17px]' : 'text-[15.5px]'}`}>
                      <a href={a.url} target="_blank" rel="noopener noreferrer"
                        className="text-navy-900 hover:underline underline-offset-4">{a.title}</a>
                    </h3>
                    {a.summary && <p className="mt-1.5 text-sm leading-relaxed text-muted max-w-3xl">{a.summary}</p>}
                    <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
                      {a.is_key && <span className="badge bg-red-50 text-red-700 border border-red-200">주요</span>}
                      <span className={`badge border ${CAT_STYLE[a.category] || 'bg-slate-50 text-slate-600 border-slate-200'}`}>
                        {a.category}
                      </span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}

          {data.collected_at && (
            <p className="mt-6 text-xs text-muted">
              갱신 {new Date(data.collected_at).toLocaleString('ko-KR')}
              {data.generator ? ` · ${data.generator}` : ''}
            </p>
          )}
        </>
      )}
    </CareLayout>
  )
}

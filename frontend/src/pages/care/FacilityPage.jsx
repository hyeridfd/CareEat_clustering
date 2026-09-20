import { useEffect, useState } from 'react'
import api from '../../lib/api'
import CareLayout from '../../components/care/CareLayout'
import { errMsg } from '../../components/care/CareUI'

/* Care-Eat Scan — 시설 영양 프로파일
   개인 평가를 시설 단위로 집계해 "우리 시설은 무엇이 문제인가"를 보여준다. */

const TONE = (pct, cut = [15, 30]) =>
  pct == null ? 'bg-slate-200' : pct >= cut[1] ? 'bg-rose-500' : pct >= cut[0] ? 'bg-amber-500' : 'bg-navy-500'

function Stat({ label, value, unit, sub, tone }) {
  return (
    <div className={`rounded-2xl px-4 py-3.5 ${tone || 'bg-navy-50/70'}`}>
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-1 text-2xl font-extrabold tabular-nums text-navy-900">
        {value ?? '–'}<span className="ml-0.5 text-xs font-normal text-muted">{unit}</span>
      </p>
      {sub && <p className="mt-0.5 text-[11px] text-muted">{sub}</p>}
    </div>
  )
}

function Section({ title, sub, right, children }) {
  return (
    <section className="surface p-6">
      <header className="flex flex-wrap items-end justify-between gap-2 mb-4">
        <div>
          <h2 className="text-base font-extrabold text-navy-900">{title}</h2>
          {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  )
}

/* 비율 막대 — 위험군·질환처럼 '몇 %가 해당되는가' */
function RatioRows({ rows, cut, empty = '해당 항목이 없습니다.' }) {
  const shown = rows.filter((r) => r.pct)
  if (!shown.length) return <p className="text-sm text-muted py-2">{empty}</p>
  return (
    <div className="space-y-2">
      {shown.map((r) => (
        <div key={r.key || r.name} className="flex items-center gap-3">
          <span className="w-52 shrink-0 text-xs text-gray-700 truncate">{r.label || r.name}</span>
          <div className="relative h-3 flex-1 rounded-full bg-navy-50 min-w-0">
            <div className={`absolute inset-y-0 left-0 rounded-full ${TONE(r.pct, cut)}`}
              style={{ width: `${Math.max(2, Math.min(100, r.pct))}%` }} />
          </div>
          <span className="w-24 shrink-0 text-right text-[11px] tabular-nums text-muted">
            <b className="text-navy-900">{r.pct}%</b> · {r.n}명
          </span>
        </div>
      ))}
    </div>
  )
}

/* 섭취율 막대 — 낮을수록 문제 */
function IntakeRows({ rows, labelKey = 'label' }) {
  if (!rows?.length) return <p className="text-sm text-muted py-2">식사 기록이 없습니다.</p>
  return (
    <div className="space-y-2">
      {rows.map((r, i) => (
        <div key={i} className="flex items-center gap-3">
          <span className="w-28 shrink-0 text-xs text-gray-700 truncate">{r[labelKey]}</span>
          <div className="relative h-3 flex-1 rounded-full bg-navy-50 min-w-0">
            <div className={`absolute inset-y-0 left-0 rounded-full ${r.rate ?? r.value ? ((r.rate ?? r.value) < 60 ? 'bg-rose-500' : (r.rate ?? r.value) < 80 ? 'bg-amber-500' : 'bg-navy-500') : 'bg-slate-200'}`}
              style={{ width: `${Math.max(2, Math.min(100, r.rate ?? r.value ?? 0))}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right text-[11px] tabular-nums text-muted">
            <b className="text-navy-900">{r.rate ?? r.value ?? '–'}%</b>{r.n ? ` · ${r.n}` : ''}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function FacilityPage() {
  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  const load = (refresh = false) => {
    setBusy(true)
    api.get('/care/facility/profile', { params: refresh ? { refresh: true } : {}, timeout: 60000 })
      .then((r) => { setD(r.data); setErr('') })
      .catch((e) => setErr(errMsg(e)))
      .finally(() => setBusy(false))
  }
  useEffect(() => { load() }, [])

  const risk = (k) => d?.risks?.find((x) => x.key === k)?.pct

  return (
    <CareLayout
      title="시설 진단"
      subtitle="입소자 평가를 시설 단위로 모아, 급식·영양 운영에서 무엇부터 봐야 할지 정리합니다."
      actions={<button onClick={() => load(true)} disabled={busy} className="btn-secondary text-sm">{busy ? '집계 중…' : '다시 집계'}</button>}
    >
      {err && <p className="surface p-6 text-red-700">{err}</p>}
      {!err && !d && <div className="surface p-12 text-center text-muted">불러오는 중…</div>}

      {d && (
        <div className="space-y-5">
          <Section title="한눈에 보기"
            sub={`어르신 ${d.n_residents}명 중 ${d.n_assessed}명 평가 완료${d.assessed_on ? ` · 최근 평가 ${d.assessed_on}` : ''}`}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Stat label="평가 완료율" value={d.coverage_pct} unit="%" sub={`${d.n_assessed} / ${d.n_residents}명`} />
              <Stat label="평균 식사 섭취율" value={d.intake?.total} unit="%" sub={`기록 ${d.intake?.n}명`} />
              <Stat label="영양불량 위험" value={risk('malnutrition_risk')} unit="%" tone="bg-amber-50" />
              <Stat label="식형태 조정 필요" value={risk('texture_need')} unit="%" tone="bg-sky-50" />
            </div>
            {d.types?.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {d.types.map((t) => (
                  <span key={t.name} className="badge bg-navy-50 text-navy-700">{t.name} {t.n}명 ({t.pct}%)</span>
                ))}
              </div>
            )}
          </Section>

          <div className="grid lg:grid-cols-2 gap-5">
            <Section title="위험군 분포" sub="평가 완료자 기준. 비율이 높을수록 시설 차원의 대응이 필요합니다.">
              <RatioRows rows={d.risks || []} cut={[15, 30]} />
            </Section>

            <Section title="진단 질환" sub="입소자에게 기록된 질환입니다.">
              <RatioRows rows={(d.diseases || []).map((x) => ({ ...x, key: x.name }))} cut={[20, 40]}
                empty="기록된 질환이 없습니다." />
            </Section>
          </div>

          <Section title="영양소 기준 미달·초과"
            sub="2025 한국인 영양소 섭취기준 대비 80% 미만인 어르신의 비율입니다. 나트륨만 130% 초과 기준입니다.">
            <RatioRows rows={(d.nutrients || []).map((x) => ({
              ...x, label: `${x.label} ${x.direction}`,
            }))} cut={[30, 50]} empty="섭취 영양소가 계산된 어르신이 없습니다." />
          </Section>

          <div className="grid lg:grid-cols-3 gap-5">
            <Section title="끼니별 섭취율">
              <IntakeRows rows={d.menus?.by_meal || []} />
            </Section>
            <Section title="음식군별 섭취율">
              <IntakeRows rows={d.intake?.components || []} />
            </Section>
            <Section title="식형태군별 섭취율" sub="식형태 표준화가 필요한지 확인합니다.">
              <IntakeRows rows={d.groups?.by_texture || []} />
            </Section>
          </div>

          <Section title="잔반이 많은 메뉴"
            sub="일자·끼니·음식군 단위로 시설 전체 평균 섭취율이 낮은 순입니다. 식단 개편 후보입니다."
            right={d.menus?.n_cells ? <span className="text-xs text-muted">전체 {d.menus.n_cells}칸</span> : null}>
            {d.menus?.worst?.length ? (
              <div className="overflow-x-auto">
                <table className="w-full text-sm min-w-[520px]">
                  <thead>
                    <tr className="text-left text-[11px] text-muted border-b border-navy-100">
                      <th className="py-2">일자</th><th className="py-2">끼니</th><th className="py-2">음식군</th>
                      <th className="py-2">메뉴</th><th className="py-2 text-right">평균 섭취율</th><th className="py-2 text-right">인원</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.menus.worst.map((m, i) => (
                      <tr key={i} className="border-b border-navy-50 last:border-0">
                        <td className="py-2 whitespace-nowrap">{m.day}일차</td>
                        <td className="py-2 whitespace-nowrap">{m.meal_label}</td>
                        <td className="py-2 whitespace-nowrap text-muted">{m.slot_label}</td>
                        <td className="py-2 font-semibold text-navy-900">{m.menu || '—'}</td>
                        <td className={`py-2 text-right tabular-nums font-bold ${m.rate < 60 ? 'text-rose-600' : m.rate < 80 ? 'text-amber-700' : 'text-navy-900'}`}>{m.rate}%</td>
                        <td className="py-2 text-right tabular-nums text-muted">{m.n}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="text-sm text-muted py-2">식사 기록이 아직 없습니다.</p>}
          </Section>

          <p className="text-[11px] text-muted px-1">
            이 화면은 Care-Eat Scan 단계입니다. 다음 단계(Insight)에서는 여기 지표를 근거로
            시설의 관리 우선순위를 자동으로 매기고, 지침에 근거한 운영 개선안을 제시합니다.
          </p>
        </div>
      )}
    </CareLayout>
  )
}

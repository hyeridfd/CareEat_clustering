import { PfmlLogo } from '../brand/Brand'

// 유형 색 (dataviz 검증 통과 팔레트: 인접 대비 ΔE 기준 충족)
const TYPE_COLORS = ['#1151b8', '#d97706', '#e11d48', '#6d28d9', '#0f9d76', '#475569']
const TONE = {
  good: { chip: 'bg-emerald-50 text-emerald-700 ring-emerald-200', dot: 'bg-emerald-500', icon: '●' },
  warn: { chip: 'bg-amber-50 text-amber-800 ring-amber-200', dot: 'bg-amber-500', icon: '▲' },
  bad: { chip: 'bg-rose-50 text-rose-700 ring-rose-200', dot: 'bg-rose-500', icon: '■' },
  none: { chip: 'bg-slate-100 text-slate-500 ring-slate-200', dot: 'bg-slate-300', icon: '–' },
}

function Section({ no, title, sub, children, right }) {
  return (
    <section className="surface p-6 md:p-8">
      <header className="flex flex-wrap items-start justify-between gap-3 mb-5">
        <div>
          {no && <span className="text-[11px] font-extrabold tracking-[0.18em] text-navy-400">{no}</span>}
          <h2 className="text-lg font-extrabold text-navy-900 leading-snug">{title}</h2>
          {sub && <p className="mt-1 text-xs text-muted">{sub}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  )
}

function Field({ label, value, hint }) {
  return (
    <div className="rounded-xl bg-navy-50/60 px-4 py-3">
      <p className="text-[11px] text-muted">{label}</p>
      <p className="mt-0.5 text-[15px] font-bold text-navy-900">{value ?? '–'}</p>
      {hint && <p className="mt-0.5 text-[11px] text-muted">{hint}</p>}
    </div>
  )
}

/* 가로 막대: 값 + (선택) 시설 평균 기준선 */
function CompareBar({ label, value, avg, min = 0, max = 100, unit = '' }) {
  const pct = (v) => Math.max(0, Math.min(100, ((v - min) / (max - min)) * 100))
  return (
    <div className="py-2.5">
      <div className="flex items-baseline justify-between gap-3 mb-1.5">
        <span className="text-sm font-medium text-navy-900">{label}</span>
        <span className="text-sm font-bold tabular-nums text-navy-900">
          {value}{unit}
          {avg != null && <span className="ml-2 text-xs font-medium text-muted">시설 평균 {avg}{unit}</span>}
        </span>
      </div>
      <div className="relative h-3 rounded-full bg-navy-50">
        <div className="absolute inset-y-0 left-0 rounded-full bg-navy-600" style={{ width: `${pct(value)}%` }} />
        {avg != null && (
          <span className="absolute top-[-3px] h-[18px] w-[2px] rounded bg-slate-500" style={{ left: `${pct(avg)}%` }} title={`시설 평균 ${avg}${unit}`} />
        )}
      </div>
    </div>
  )
}

/* 세로 막대: 끼니별·음식별 섭취율 */
function RateBars({ items, caption }) {
  const shown = items.filter((x) => x.value != null)
  if (shown.length === 0) return <p className="text-sm text-muted">기록된 식사 데이터가 없습니다.</p>
  return (
    <div>
      <div className="flex items-end gap-3 h-36">
        {shown.map((x) => {
          const low = x.value < 70
          return (
            <div key={x.label} className="flex-1 flex flex-col items-center justify-end gap-2">
              <span className={`text-xs font-bold tabular-nums ${low ? 'text-rose-600' : 'text-navy-900'}`}>{x.value}%</span>
              <div className="w-full rounded-t-[4px] rounded-b-none" style={{
                height: `${Math.max(4, x.value)}%`,
                background: low ? '#e11d48' : '#1151b8',
              }} />
              <span className="text-[11px] text-muted">{x.label}</span>
            </div>
          )
        })}
      </div>
      {caption && <p className="mt-3 text-xs text-muted">{caption}</p>}
    </div>
  )
}

/* 도넛: 시설 내 유형 분포 */
function TypeDonut({ distribution, total }) {
  const R = 54, C = 2 * Math.PI * R
  let offset = 0
  return (
    <div className="flex flex-wrap items-center gap-6">
      <svg viewBox="0 0 140 140" className="w-[140px] h-[140px] shrink-0" role="img" aria-label="시설 내 유형 분포">
        <g transform="translate(70,70) rotate(-90)">
          {distribution.map((d, i) => {
            const frac = total ? d.count / total : 0
            const len = frac * C
            const el = (
              <circle key={d.code} r={R} fill="none" stroke={TYPE_COLORS[i % TYPE_COLORS.length]}
                strokeWidth={d.is_self ? 20 : 14} strokeDasharray={`${Math.max(0, len - 2)} ${C - Math.max(0, len - 2)}`}
                strokeDashoffset={-offset} opacity={d.is_self ? 1 : 0.55} />
            )
            offset += len
            return el
          })}
        </g>
        <text x="70" y="66" textAnchor="middle" className="fill-navy-900" style={{ fontSize: 20, fontWeight: 800 }}>{total}</text>
        <text x="70" y="84" textAnchor="middle" className="fill-slate-500" style={{ fontSize: 10 }}>명</text>
      </svg>
      <ul className="space-y-2 text-sm">
        {distribution.map((d, i) => (
          <li key={d.code} className="flex items-center gap-2">
            <span className="w-3 h-3 rounded-sm" style={{ background: TYPE_COLORS[i % TYPE_COLORS.length], opacity: d.is_self ? 1 : 0.55 }} />
            <span className={d.is_self ? 'font-bold text-navy-900' : 'text-slate-600'}>{d.name || d.code}</span>
            <span className="text-muted tabular-nums">{d.count}명</span>
            {d.is_self && <span className="badge bg-navy-600 text-white">해당</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function Stars({ value }) {
  if (value == null) return <span className="text-sm text-muted">–</span>
  return (
    <span className="inline-flex items-center gap-1">
      <span className="text-amber-500 tracking-tight" aria-hidden>
        {'★'.repeat(Math.round(value))}<span className="text-slate-200">{'★'.repeat(5 - Math.round(value))}</span>
      </span>
      <span className="text-sm font-bold tabular-nums text-navy-900">{value}</span>
      <span className="text-xs text-muted">/ 5</span>
    </span>
  )
}

export default function ReportView({ r }) {
  const staff = r.audience === 'staff'
  const res = r.resident
  const sol = r.solution || {}

  return (
    <div className="space-y-5">
      {/* 표지 */}
      <section className="rounded-2xl bg-navy-grad text-white p-7 md:p-9">
        <p className="text-xs font-semibold text-sky-200">{r.facility?.name}</p>
        <h1 className="mt-2 text-2xl md:text-3xl font-extrabold tracking-tight leading-snug">
          {res.display_name} 어르신<br />건강·식사 돌봄 리포트
        </h1>
        <div className="mt-5 flex flex-wrap gap-x-6 gap-y-1 text-sm text-navy-100/85">
          {res.age != null && <span>{res.age}세 {res.gender}</span>}
          {res.care_grade && <span>장기요양 {res.care_grade}</span>}
          <span>평가일 {r.assessed_on}</span>
          {r.guardian_name && <span>{r.guardian_name}님께</span>}
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-2">
          <span className="badge bg-white/15 text-white ring-1 ring-white/20">
            {staff ? `${r.type?.code} · ${r.type?.name}` : `관리 구분 · ${r.type?.guardian_label || r.type?.name}`}
          </span>
          {staff && r.priority && (
            <span className="badge bg-white text-navy-800">
              돌봄 우선순위 {Math.round(r.priority.score)}점 · {{ high: '우선 관리', medium: '주의 관찰', low: '정기 관리' }[r.priority.level]}
            </span>
          )}
          {staff && r.is_borderline && <span className="badge bg-violet-100 text-violet-800">경계 사례</span>}
        </div>
      </section>

      {/* 한눈에 보기 */}
      <Section title="한눈에 보기" sub={staff ? '괄호 안은 평가 도구와 점수입니다.' : '어르신의 현재 상태를 단계로 정리했습니다.'}>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          {r.statuses.map((s) => {
            const t = TONE[s.tone] || TONE.none
            return (
              <div key={s.key} className={`rounded-2xl ring-1 px-4 py-4 ${t.chip}`}>
                <p className="text-[11px] font-semibold opacity-80">{s.label}</p>
                <p className="mt-1 text-[17px] font-extrabold leading-tight">
                  <span className="mr-1 text-[11px] align-middle" aria-hidden>{t.icon}</span>{s.label === '미실시' ? '–' : s.label}
                </p>
                {staff && s.value != null && <p className="mt-1 text-[11px] opacity-80">{s.scale} · {s.value}</p>}
              </div>
            )
          })}
        </div>
      </Section>

      {/* 유형 */}
      <Section title={staff ? '유형 분류' : '어르신의 관리 구분'}
        sub={staff ? `${r.facility?.name} 어르신 ${r.type?.peer_total}명 기준` : '비슷한 상태의 어르신끼리 묶어 돌봄 방향을 정합니다.'}>
        <div className="rounded-2xl bg-navy-50/70 px-5 py-4 mb-5">
          <p className="text-sm font-extrabold text-navy-900">
            {staff ? `${r.type?.code} · ${r.type?.name}` : r.type?.guardian_label || r.type?.name}
          </p>
          {r.type?.description && <p className="mt-1.5 text-sm leading-6 text-slate-600">{r.type.description}</p>}
        </div>
        <TypeDonut distribution={r.type?.distribution || []} total={r.type?.peer_total || 0} />
      </Section>

      {/* 시설 평균 대비 */}
      {r.comparison?.length > 0 && (
        <Section no="01" title="시설 평균과 비교" sub="파란 막대가 어르신, 회색 선이 같은 시설 어르신들의 평균입니다.">
          <div className="divide-y divide-navy-50">
            {r.comparison.map((c) => <CompareBar key={c.label} {...c} value={c.self} avg={c.facility_avg} />)}
          </div>
        </Section>
      )}

      {/* 기본 정보 */}
      <Section no="02" title="기본 정보와 식사 특성">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Field label="식사 형태" value={res.meal_form} />
          <Field label="식사 도움" value={res.eating} />
          <Field label="씹기" value={res.chewing ? '어려움 있음' : '불편 없음'} />
          <Field label="삼키기" value={res.swallowing ? '어려움 있음' : '불편 없음'} />
          {staff && <Field label="학력" value={res.education} />}
          {staff && <Field label="장기요양등급" value={res.care_grade} />}
        </div>
      </Section>

      {/* 질환·약물 */}
      {(res.diseases?.length > 0 || res.medications?.length > 0) && (
        <Section no="03" title="건강 상태" sub="조사 시점에 기록된 내용입니다.">
          <div className="grid md:grid-cols-2 gap-5">
            <div>
              <p className="text-xs font-semibold text-muted mb-2">보유 질환</p>
              <div className="flex flex-wrap gap-1.5">
                {res.diseases?.length ? res.diseases.map((d) => <span key={d} className="badge bg-navy-50 text-navy-700">{d}</span>)
                  : <span className="text-sm text-muted">기록 없음</span>}
              </div>
            </div>
            <div>
              <p className="text-xs font-semibold text-muted mb-2">복용 약물</p>
              <div className="flex flex-wrap gap-1.5">
                {res.medications?.length ? res.medications.map((d) => <span key={d} className="badge bg-slate-100 text-slate-700">{d}</span>)
                  : <span className="text-sm text-muted">기록 없음</span>}
              </div>
            </div>
          </div>
        </Section>
      )}

      {/* 신체 계측 */}
      <Section no="04" title="신체 계측">
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Field label="키" value={r.anthropometry.height ? `${r.anthropometry.height} cm` : null} />
          <Field label="몸무게" value={r.anthropometry.weight ? `${r.anthropometry.weight} kg` : null}
            hint={r.anthropometry.weight_change != null ? `직전 평가 대비 ${r.anthropometry.weight_change > 0 ? '+' : ''}${r.anthropometry.weight_change}kg` : null} />
          <Field label="체질량지수" value={r.anthropometry.bmi} hint={r.anthropometry.bmi_band?.label} />
          <Field label="혈압" value={r.anthropometry.sbp ? `${r.anthropometry.sbp} / ${r.anthropometry.dbp}` : null} hint="mmHg" />
          <Field label="식사 섭취율" value={r.intake.total != null ? `${r.intake.total}%` : null} hint={r.intake.band?.label} />
        </div>
      </Section>

      {/* 실제로 드신 양 */}
      <Section no="05" title="실제로 드신 양"
        sub={r.intake.days ? `${r.intake.days}일 동안 끼니마다 남긴 양을 기록해 계산했습니다.` : '식사 기록을 바탕으로 계산했습니다.'}>
        {!r.intake.has_nutrition && <p className="mb-4 text-sm rounded-xl bg-amber-50 text-amber-800 px-4 py-3">식사(잔반) 조사가 아직 완료되지 않아 추정값입니다.</p>}
        <div className="grid md:grid-cols-2 gap-8">
          <div>
            <p className="text-xs font-semibold text-muted mb-3">끼니별 섭취율</p>
            <RateBars items={r.intake.meals}
              caption={r.intake.low_meals?.length ? `${r.intake.low_meals.join(', ')}에 특히 적게 드셨습니다.` : '끼니별로 고르게 드시고 있습니다.'} />
          </div>
          <div>
            <p className="text-xs font-semibold text-muted mb-3">음식 종류별 섭취율</p>
            <RateBars items={r.intake.components} caption="주찬은 단백질 반찬입니다." />
          </div>
        </div>
        {r.intake.prev_total != null && (
          <p className="mt-5 text-sm text-slate-600">
            직전 평가 {r.intake.prev_total}% → 이번 {r.intake.total}%
            <span className={`ml-2 font-semibold ${r.intake.total >= r.intake.prev_total ? 'text-emerald-700' : 'text-rose-700'}`}>
              {r.intake.total >= r.intake.prev_total ? '증가' : '감소'}
            </span>
          </p>
        )}
        <p className="mt-4 text-xs text-muted">영양소(에너지·단백질 등) 충족률은 식품 영양성분 연계 후 제공될 예정입니다.</p>
      </Section>

      {/* 만족·선호 */}
      <Section no="06" title="급식 만족도와 음식 선호">
        <div className="grid md:grid-cols-3 gap-4">
          <div className="rounded-xl bg-navy-50/60 px-4 py-3"><p className="text-[11px] text-muted">전반 만족</p><Stars value={r.satisfaction.overall} /></div>
          <div className="rounded-xl bg-navy-50/60 px-4 py-3"><p className="text-[11px] text-muted">양 적절성</p><Stars value={r.satisfaction.portion} /></div>
          <div className="rounded-xl bg-navy-50/60 px-4 py-3"><p className="text-[11px] text-muted">맛·품질</p><Stars value={r.satisfaction.quality} /></div>
        </div>
        {r.satisfaction.prefs?.length > 0 && (
          <div className="mt-5">
            <p className="text-xs font-semibold text-muted mb-2">좋아하시는 음식</p>
            <div className="flex flex-wrap gap-1.5">
              {r.satisfaction.prefs.map((p) => <span key={p} className="badge bg-sky-50 text-sky-700">{p}</span>)}
            </div>
          </div>
        )}
        {r.satisfaction.comment && (
          <p className="mt-5 rounded-xl bg-white ring-1 ring-navy-100 px-4 py-3 text-sm leading-6 text-slate-700">
            “{r.satisfaction.comment}”
          </p>
        )}
      </Section>

      {/* 돌봄 제안 */}
      <Section title="돌봄 제안" sub={staff ? '규칙 근거를 바탕으로 만든 제안이며, 담당자 승인 후 적용됩니다.' : '시설에서 이렇게 돌봐 드리고 있습니다.'}>
        {!staff && sol.guardian_message && (
          <p className="rounded-2xl bg-navy-50/70 px-5 py-4 text-[15px] leading-7 text-navy-900 whitespace-pre-line">{sol.guardian_message}</p>
        )}
        {staff && sol.summary && <p className="text-[15px] leading-7 text-navy-900">{sol.summary}</p>}

        {sol.actions?.length > 0 && (
          <ol className="mt-5 space-y-3">
            {sol.actions.map((a, i) => (
              <li key={i} className="rounded-2xl ring-1 ring-navy-100 p-5">
                <div className="flex items-center gap-2">
                  <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-navy-600 text-white text-xs font-bold">{i + 1}</span>
                  <span className="text-xs font-bold text-navy-600">{a.category}</span>
                </div>
                <p className="mt-2 text-[15px] leading-7 text-navy-900">{a.action}</p>
                {a.why && <p className="mt-2 text-xs leading-5 text-muted"><b className="text-navy-500">WHY</b> {a.why}</p>}
              </li>
            ))}
          </ol>
        )}

        {sol.meal_guidance?.length > 0 && (
          <div className="mt-6">
            <p className="text-xs font-semibold text-muted mb-2">식사는 이렇게 준비합니다</p>
            <ul className="space-y-1.5">
              {sol.meal_guidance.map((x, i) => (
                <li key={i} className="flex gap-2 text-sm leading-6 text-slate-700"><span className="text-navy-500">•</span><span>{x}</span></li>
              ))}
            </ul>
          </div>
        )}
        {sol.monitoring?.length > 0 && (
          <div className="mt-5">
            <p className="text-xs font-semibold text-muted mb-2">이렇게 지켜보고 있습니다</p>
            <ul className="space-y-1.5">
              {sol.monitoring.map((x, i) => (
                <li key={i} className="flex gap-2 text-sm leading-6 text-slate-700"><span className="text-navy-500">•</span><span>{x}</span></li>
              ))}
            </ul>
          </div>
        )}
        {!sol.actions?.length && !sol.guardian_message && <p className="text-sm text-muted">아직 만들어진 돌봄 계획이 없습니다.</p>}
      </Section>

      {/* 담당자 전용 */}
      {staff && r.priority?.factors?.length > 0 && (
        <Section title="돌봄 우선순위 근거" sub="점수는 유형 위험도, 현재 상태, 직전 평가 대비 변화를 더한 값입니다.">
          <ul className="divide-y divide-navy-50">
            {r.priority.factors.map((x) => (
              <li key={x.code} className="flex items-start justify-between gap-3 py-2.5 text-sm">
                <span className="text-slate-700">
                  {x.kind === 'trend' && <span className="mr-1 badge bg-rose-50 text-rose-600">변화</span>}
                  {x.label}{x.value != null && typeof x.value !== 'boolean' && x.value !== 1 ? <span className="text-muted"> · {x.value}</span> : null}
                </span>
                <span className={`shrink-0 text-xs font-bold tabular-nums ${x.points ? 'text-navy-900' : 'text-slate-300'}`}>+{x.points}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {staff && r.history?.length > 1 && (
        <Section title="평가 이력">
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[420px]">
              <thead><tr className="text-left text-xs text-muted border-b border-navy-100">
                <th className="py-2">평가일</th><th className="py-2">유형</th><th className="py-2 text-right">섭취율</th>
                <th className="py-2 text-right">체중</th><th className="py-2 text-right">영양 점수</th></tr></thead>
              <tbody>
                {r.history.map((h, i) => (
                  <tr key={i} className="border-b border-navy-50 last:border-0">
                    <td className="py-2">{h.created_at}</td><td className="py-2">{h.type_code}</td>
                    <td className="py-2 text-right tabular-nums">{h.intake_total ?? '–'}%</td>
                    <td className="py-2 text-right tabular-nums">{h.weight_kg ?? '–'}kg</td>
                    <td className="py-2 text-right tabular-nums">{h.mna_sf ?? '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}

      {/* 안내 */}
      <section className="rounded-2xl border border-navy-100 bg-navy-50/40 p-6">
        <p className="text-xs leading-6 text-muted">
          이 리포트는 시설에서 기록한 조사 자료를 바탕으로 만들어졌으며, <b className="text-navy-900">의학적 진단이나 치료 지침이 아닙니다.</b>
          건강에 관한 판단이 필요한 경우 시설 간호 인력 또는 의료진과 상의해 주세요.
          {r.expires_on && <> 이 페이지는 {r.expires_on}까지 열람할 수 있습니다.</>}
        </p>
        <div className="mt-5 flex items-center gap-3">
          <PfmlLogo className="h-7" />
          <span className="text-[11px] leading-4 text-muted">
            서울대학교 농생명공학부<br />정밀식의약솔루션 연구실 · Care-Eat
            {r.model_version && <> · 유형 모델 {r.model_version}</>}
          </span>
        </div>
      </section>
    </div>
  )
}

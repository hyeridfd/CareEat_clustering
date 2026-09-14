import { Link } from 'react-router-dom'
import { LogoMark, PfmlLogo, PublicFooter, PublicHeader } from '../components/brand/Brand'

const STEPS = [
  {
    id: 'record', no: '01', title: '기록',
    lead: '어르신의 건강과 식사를 한곳에',
    body: '입소 시 건강 프로파일(질환·씹기·삼키기·기능 상태)과 식사 섭취, 급식 만족·선호를 태블릿으로 기록합니다. 척도 점수는 자동으로 계산돼요.',
    points: ['건강 프로파일 조사', '끼니별 섭취·잔반 기록', '급식 만족·음식 선호'],
  },
  {
    id: 'diagnose', no: '02', title: '진단',
    lead: '질환명이 아니라 돌봄 수요로 나눕니다',
    body: '영양·기능·인지·구강·섭취·만족을 함께 넣어 어르신을 유형으로 분류하고, 돌봄 우선순위를 점수로 보여줍니다. 상태가 달라지면 유형 변화도 자동으로 알려요.',
    points: ['데이터 기반 유형 분류', '돌봄 우선순위 점수', '유형 변화·경계 사례 감지'],
  },
  {
    id: 'solution', no: '03', title: '솔루션',
    lead: '유형에 맞는 돌봄을 제안합니다',
    body: '유형과 위험 요인에 맞춰 식사 형태, 식사 도움, 관찰 항목을 정리한 돌봄 계획을 만듭니다. 모든 제안은 담당자가 확인하고 승인한 뒤에 적용돼요.',
    points: ['LLM 기반 돌봄 솔루션', '맞춤 식단 설계 (준비 중)', '맞춤 프로그램 추천 (준비 중)'],
  },
  {
    id: 'connect', no: '04', title: '보호자 소통',
    lead: '가족이 안심할 수 있게',
    body: '승인된 내용만 보호자에게 문자로 전해집니다. 점수나 어려운 용어 없이, 어르신이 어떻게 지내고 시설이 무엇을 하고 있는지 쉬운 말로 안내해요.',
    points: ['문자 기반 안내', '보호자 전용 리포트 링크', '수신 동의 관리·발송 기록'],
  },
]

const TYPES = [
  { code: 'C1', name: '양호 기능·양호 섭취형', label: '안정 관리군', desc: '기능과 식사가 모두 안정적인 어르신. 현재 식사를 유지하며 정기적으로 확인합니다.', tone: 'from-sky-50 to-white ring-sky-200 text-sky-700' },
  { code: 'C2', name: '섭취 저조·급식 불만족형', name2: '식사 관심군', desc: '식사량이 적고 입맛에 맞지 않는 어르신. 원인을 찾아 선호를 반영하고 소량씩 자주 제공합니다.', tone: 'from-amber-50 to-white ring-amber-200 text-amber-700' },
  { code: 'C3', name: '저작·연하곤란 고위험형', name2: '집중 돌봄군', desc: '씹기·삼키기가 어렵고 영양 위험이 큰 어르신. 식사 형태와 자세를 조정하고 체중을 자주 확인합니다.', tone: 'from-rose-50 to-white ring-rose-200 text-rose-700' },
]

function Icon({ name, className = 'w-5 h-5' }) {
  const p = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' }
  const paths = {
    record: <><rect x="4" y="3" width="16" height="18" rx="3" {...p} /><path d="M8 8h8M8 12h8M8 16h5" {...p} /></>,
    diagnose: <><circle cx="8" cy="9" r="3" {...p} /><circle cx="16" cy="15" r="3" {...p} /><path d="M11 9h3M10 15H7" {...p} /></>,
    solution: <><path d="M12 3a6 6 0 0 0-3 11.2V17h6v-2.8A6 6 0 0 0 12 3z" {...p} /><path d="M10 20h4" {...p} /></>,
    connect: <><path d="M4 7a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v6a3 3 0 0 1-3 3H9l-5 4V7z" {...p} /></>,
    check: <path d="M5 12.5l4.2 4.2L19 7" {...p} />,
    shield: <><path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6l7-3z" {...p} /><path d="M9 12l2.2 2.2L15.5 10" {...p} /></>,
  }
  return <svg viewBox="0 0 24 24" className={className}>{paths[name]}</svg>
}

export default function LandingPage() {
  return (
    <div className="bg-white">
      <PublicHeader />

      {/* HERO */}
      <section className="relative overflow-hidden bg-navy-grad text-white">
        <div aria-hidden className="absolute inset-0 opacity-[0.14]"
          style={{ backgroundImage: 'radial-gradient(circle at 20% 20%, #ffffff 1px, transparent 1px)', backgroundSize: '26px 26px' }} />
        <div className="relative max-w-6xl mx-auto px-5 pt-20 pb-24 md:pt-28 md:pb-32">
          <div className="max-w-3xl">
            <span className="inline-flex items-center gap-2 rounded-full bg-white/10 ring-1 ring-white/20 px-3 py-1 text-xs font-semibold text-sky-200">
              서울대학교 정밀식의약솔루션 연구실
            </span>
            <h1 className="mt-6 text-[34px] leading-[1.25] md:text-[52px] md:leading-[1.15] font-extrabold tracking-tight">
              어르신 한 분 한 분에게<br />
              <span className="text-sky-300">맞는 식사와 돌봄</span>을 찾아냅니다
            </h1>
            <p className="mt-6 text-[15px] md:text-lg text-navy-100/85 leading-relaxed max-w-2xl">
              Care-Eat은 요양시설의 건강·식사 기록을 모아 어르신을 유형으로 진단하고,
              그에 맞는 돌봄 계획과 보호자 안내까지 이어 주는 플랫폼입니다.
            </p>
            <div className="mt-9 flex flex-wrap gap-3">
              <Link to="/signup" className="btn-lg bg-white text-navy-800 font-bold hover:bg-sky-50 shadow-lift">시설 가입 신청</Link>
              <Link to="/staff-login" className="btn-lg bg-white/10 text-white ring-1 ring-white/25 hover:bg-white/15 font-semibold">담당자 로그인</Link>
            </div>
            <p className="mt-5 text-xs text-navy-100/60">
              가입 신청 후 연구실 확인을 거쳐 담당자 계정이 발급됩니다.
            </p>
          </div>
        </div>
        <div className="relative max-w-6xl mx-auto px-5 pb-14">
          <div className="grid gap-3 sm:grid-cols-4">
            {STEPS.map((s) => (
              <a key={s.id} href={`#${s.id}`}
                className="group rounded-2xl bg-white/10 ring-1 ring-white/15 px-4 py-4 hover:bg-white/15 transition">
                <span className="flex items-center gap-2 text-sky-200"><Icon name={s.id} /><span className="text-xs font-bold tracking-widest">{s.no}</span></span>
                <p className="mt-2 font-bold text-white">{s.title}</p>
                <p className="text-xs text-navy-100/70 mt-0.5">{s.lead}</p>
              </a>
            ))}
          </div>
        </div>
      </section>

      {/* 왜 필요한가 */}
      <section className="max-w-6xl mx-auto px-5 py-20">
        <div className="grid md:grid-cols-2 gap-10 md:gap-16 items-start">
          <div>
            <p className="eyebrow">왜 Care-Eat 인가</p>
            <h2 className="mt-3 text-3xl font-extrabold tracking-tight text-navy-900 leading-snug">
              같은 치매 어르신이라도<br />필요한 식사는 다릅니다
            </h2>
            <p className="mt-5 text-[15px] leading-7 text-slate-600">
              진단명만으로는 어떤 식사와 돌봄이 필요한지 알기 어렵습니다.
              Care-Eat은 영양 상태, 기능 수준, 씹고 삼키는 능력, 실제로 얼마나 드시는지, 급식에 만족하는지를
              함께 보고 어르신을 유형으로 나눕니다. 현장에서 누구를 먼저 챙겨야 하는지가 분명해집니다.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {[
              { v: '5개', k: '영역 통합 분석', d: '영양·기능 / 인지·정서 / 구강·섭식 / 섭취 / 만족' },
              { v: '17개', k: '핵심 지표', d: 'MNA-SF, K-MBI, 섭취율 등 자동 산출' },
              { v: '0–100', k: '돌봄 우선순위', d: '상태와 최근 변화를 함께 반영한 점수' },
              { v: '100%', k: '담당자 검토', d: '모든 제안은 승인 후에만 적용·발송' },
            ].map((x) => (
              <div key={x.k} className="rounded-2xl border border-navy-100 bg-gradient-to-b from-navy-50/60 to-white p-5">
                <p className="text-2xl font-extrabold text-navy-700">{x.v}</p>
                <p className="mt-1 text-sm font-bold text-navy-900">{x.k}</p>
                <p className="mt-1 text-xs leading-5 text-muted">{x.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 4단계 */}
      <section className="bg-navy-50/50 border-y border-navy-100">
        <div className="max-w-6xl mx-auto px-5 py-20 space-y-16">
          <div className="text-center max-w-2xl mx-auto">
            <p className="eyebrow">서비스 흐름</p>
            <h2 className="mt-3 text-3xl font-extrabold tracking-tight text-navy-900">기록에서 보호자 안내까지, 한 흐름으로</h2>
            <p className="mt-4 text-[15px] text-slate-600 leading-7">
              따로 쓰던 조사지, 엑셀, 보호자 연락을 하나로 잇습니다.
            </p>
          </div>

          {STEPS.map((s, i) => (
            <div key={s.id} id={s.id} className="scroll-mt-24 grid md:grid-cols-12 gap-8 items-center">
              <div className={`md:col-span-5 ${i % 2 ? 'md:order-2' : ''}`}>
                <span className="flex items-center gap-3">
                  <span className="flex items-center justify-center w-11 h-11 rounded-2xl bg-navy-600 text-white"><Icon name={s.id} className="w-5 h-5" /></span>
                  <span>
                    <span className="block text-xs font-bold tracking-widest text-navy-400">STEP {s.no}</span>
                    <span className="block text-xl font-extrabold text-navy-900">{s.title}</span>
                  </span>
                </span>
                <h3 className="mt-5 text-2xl font-bold text-navy-900 leading-snug">{s.lead}</h3>
                <p className="mt-3 text-[15px] leading-7 text-slate-600">{s.body}</p>
                <ul className="mt-5 space-y-2">
                  {s.points.map((p) => {
                    const soon = p.includes('준비 중')
                    return (
                      <li key={p} className="flex items-center gap-2 text-sm">
                        <span className={soon ? 'text-slate-300' : 'text-navy-500'}><Icon name="check" className="w-4 h-4" /></span>
                        <span className={soon ? 'text-slate-400' : 'text-navy-900 font-medium'}>{p.replace(' (준비 중)', '')}</span>
                        {soon && <span className="badge-soon">준비 중</span>}
                      </li>
                    )
                  })}
                </ul>
              </div>
              <div className={`md:col-span-7 ${i % 2 ? 'md:order-1' : ''}`}>
                <Mock step={s.id} />
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* 유형 예시 */}
      <section className="max-w-6xl mx-auto px-5 py-20">
        <div className="text-center max-w-2xl mx-auto">
          <p className="eyebrow">진단 결과 예시</p>
          <h2 className="mt-3 text-3xl font-extrabold tracking-tight text-navy-900">어르신 유형</h2>
          <p className="mt-4 text-[15px] text-slate-600 leading-7">
            요양시설 입소 어르신 조사 자료로 도출한 유형입니다. 데이터가 쌓이면 유형 모델은 계속 개선됩니다.
          </p>
        </div>
        <div className="mt-10 grid md:grid-cols-3 gap-5">
          {TYPES.map((t) => (
            <div key={t.code} className={`rounded-2xl bg-gradient-to-b ${t.tone} ring-1 p-6`}>
              <span className="text-xs font-extrabold tracking-widest">{t.code}</span>
              <p className="mt-2 text-lg font-bold text-navy-900 leading-snug">{t.name}</p>
              <p className="mt-1 text-xs font-semibold">{t.name2 || t.label}</p>
              <p className="mt-4 text-sm leading-6 text-slate-600">{t.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* 안전장치 */}
      <section className="bg-navy-900 text-white">
        <div className="max-w-6xl mx-auto px-5 py-20 grid md:grid-cols-2 gap-12 items-center">
          <div>
            <p className="eyebrow text-sky-300">안전하게 쓰도록</p>
            <h2 className="mt-3 text-3xl font-extrabold tracking-tight leading-snug">
              AI가 대신 결정하지 않습니다
            </h2>
            <p className="mt-5 text-[15px] leading-7 text-navy-100/85">
              Care-Eat이 만드는 것은 <b className="text-white">초안</b>입니다. 담당자가 확인하고 승인해야 어르신에게 적용되고, 보호자에게도 전달됩니다.
              약·용량·진단 표현은 자동으로 걸러지고, 근거가 없는 제안은 남지 않습니다.
            </p>
          </div>
          <div className="grid sm:grid-cols-2 gap-4">
            {[
              { t: '담당자 승인 필수', d: '승인 전에는 보호자에게 나가지 않아요' },
              { t: '근거가 남는 제안', d: '어떤 지표 때문인지 화면에 함께 표시' },
              { t: '동의 기반 안내', d: '수신 동의한 보호자에게만 발송' },
              { t: '시설별 데이터 분리', d: '다른 시설의 어르신 정보는 보이지 않아요' },
            ].map((x) => (
              <div key={x.t} className="rounded-2xl bg-white/[0.07] ring-1 ring-white/10 p-5">
                <span className="text-sky-300"><Icon name="shield" /></span>
                <p className="mt-3 font-bold">{x.t}</p>
                <p className="mt-1 text-xs leading-5 text-navy-100/70">{x.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* 운영 주체 */}
      <section className="border-t border-navy-100 bg-navy-50/40">
        <div className="max-w-6xl mx-auto px-5 py-16 grid md:grid-cols-2 gap-10 items-center">
          <div>
            <p className="eyebrow">운영</p>
            <h2 className="mt-3 text-2xl font-extrabold tracking-tight text-navy-900 leading-snug">
              연구에서 출발한 서비스입니다
            </h2>
            <p className="mt-4 text-[15px] leading-7 text-slate-600">
              Care-Eat은 서울대학교 농생명공학부 정밀식의약솔루션 연구실(PFML)이 요양시설 어르신을 대상으로 수행한
              건강·식이 조사와 유형 분류 연구를 바탕으로 만들었습니다. 유형 모델은 데이터가 쌓일수록 연구실에서 검증하며 개선합니다.
            </p>
            <p className="mt-4 text-sm text-muted">도입 문의는 가입 신청서에 남겨 주시면 연락드립니다.</p>
          </div>
          <div className="flex justify-center md:justify-end">
            <div className="rounded-2xl bg-white border border-navy-100 shadow-card px-10 py-9">
              <PfmlLogo className="h-16 mx-auto" />
              <p className="mt-5 text-center text-xs text-muted leading-5">
                서울대학교 농생명공학부<br />정밀식의약솔루션 연구실
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="max-w-6xl mx-auto px-5 py-20">
        <div className="surface p-8 md:p-12 text-center">
          <LogoMark className="w-12 h-12 mx-auto" />
          <h2 className="mt-6 text-3xl font-extrabold tracking-tight text-navy-900">시설에서 먼저 써 보세요</h2>
          <p className="mt-4 text-[15px] text-slate-600 leading-7 max-w-xl mx-auto">
            가입을 신청하시면 연구실에서 기관을 확인한 뒤 담당자 계정을 보내 드립니다.
            도입 과정과 사용 방법도 함께 안내해 드려요.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link to="/signup" className="btn-primary btn-lg">시설 가입 신청</Link>
            <Link to="/login" className="btn-secondary btn-lg">조사원 설문 로그인</Link>
          </div>
        </div>
      </section>

      <PublicFooter />
    </div>
  )
}

/* ── 화면 미리보기(정적 목업) ── */
function Frame({ children, title }) {
  return (
    <div className="rounded-2xl border border-navy-100 bg-white shadow-card overflow-hidden">
      <div className="flex items-center gap-1.5 px-4 py-2.5 border-b border-navy-100 bg-navy-50/60">
        <span className="w-2.5 h-2.5 rounded-full bg-rose-300" />
        <span className="w-2.5 h-2.5 rounded-full bg-amber-300" />
        <span className="w-2.5 h-2.5 rounded-full bg-emerald-300" />
        <span className="ml-2 text-[11px] font-semibold text-navy-700">{title}</span>
      </div>
      <div className="p-5">{children}</div>
    </div>
  )
}

function Bar({ w, tone = 'bg-navy-600' }) {
  return <span className="block h-1.5 rounded-full bg-navy-100 overflow-hidden"><span className={`block h-full rounded-full ${tone}`} style={{ width: w }} /></span>
}

function Mock({ step }) {
  if (step === 'record') {
    return (
      <Frame title="기록 · 식사 섭취">
        <div className="grid grid-cols-5 gap-2 text-center">
          {['1일차', '2일차', '3일차', '4일차', '5일차'].map((d, i) => (
            <div key={d} className={`rounded-xl py-3 text-[11px] font-semibold ${i < 3 ? 'bg-navy-600 text-white' : 'bg-navy-50 text-navy-400'}`}>{d}</div>
          ))}
        </div>
        <div className="mt-4 space-y-3">
          {[['밥/죽', '다 드심', 'bg-emerald-100 text-emerald-700'], ['국/탕', '절반 남김', 'bg-amber-100 text-amber-700'], ['주찬', '조금 남김', 'bg-sky-100 text-sky-700']].map(([n, s, c]) => (
            <div key={n} className="flex items-center justify-between rounded-xl border border-navy-100 px-4 py-3">
              <span className="text-sm font-medium text-navy-900">{n}</span>
              <span className={`badge ${c}`}>{s}</span>
            </div>
          ))}
        </div>
      </Frame>
    )
  }
  if (step === 'diagnose') {
    return (
      <Frame title="진단 · 돌봄 우선순위">
        <div className="space-y-3">
          {[['김O순', 'C3 저작·연하곤란 고위험형', 92, 'bg-rose-500', '우선 관리'],
            ['이O기', 'C2 섭취 저조·급식 불만족형', 46, 'bg-amber-400', '주의 관찰'],
            ['박O자', 'C1 양호 기능·양호 섭취형', 12, 'bg-emerald-500', '정기 관리']].map(([n, t, v, tone, lv]) => (
            <div key={n} className="rounded-xl border border-navy-100 px-4 py-3">
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm font-bold text-navy-900">{n}</span>
                <span className="text-[11px] font-semibold text-muted">{lv}</span>
              </div>
              <p className="mt-0.5 text-[11px] text-muted">{t}</p>
              <div className="mt-2 flex items-center gap-2">
                <Bar w={`${v}%`} tone={tone} />
                <span className="w-7 text-right text-xs font-bold tabular-nums text-navy-900">{v}</span>
              </div>
            </div>
          ))}
        </div>
      </Frame>
    )
  }
  if (step === 'solution') {
    return (
      <Frame title="솔루션 · 돌봄 계획">
        <p className="text-xs font-semibold text-navy-500">담당자용 요약</p>
        <p className="mt-1 text-sm text-navy-900 leading-6">삼킴 어려움과 영양 위험이 함께 있어 식사 형태 조정과 체중 관찰이 필요합니다.</p>
        <div className="mt-4 space-y-2">
          {[['식사 형태·안전', '삼킴 단계에 맞는 형태·점도를 확인하고 상체를 세워 드립니다.'],
            ['영양', '고열량·고단백 간식을 추가할지 영양사와 검토합니다.'],
            ['관찰', '체중을 주 1회 측정하고 식사 중 사레를 관찰합니다.']].map(([c, d]) => (
            <div key={c} className="rounded-xl bg-navy-50/70 px-4 py-3">
              <p className="text-[11px] font-bold text-navy-600">{c}</p>
              <p className="mt-1 text-[13px] leading-5 text-navy-900">{d}</p>
            </div>
          ))}
        </div>
        <div className="mt-4 flex gap-2">
          <span className="badge bg-navy-600 text-white">담당자 승인</span>
          <span className="badge-soon">초안 · 검토 필요</span>
        </div>
      </Frame>
    )
  }
  return (
    <Frame title="보호자 소통 · 문자 안내">
      <div className="mx-auto max-w-xs rounded-2xl bg-navy-50 p-4">
        <div className="rounded-2xl bg-white shadow-sm px-4 py-3 text-[13px] leading-6 text-navy-900">
          <p className="font-bold">[○○요양원] 김O순 어르신 건강·식사 돌봄 안내</p>
          <p className="mt-2 text-slate-600">보호자님, 안녕하세요. 이번 평가 결과와 돌봄 계획을 안내드립니다.</p>
          <p className="mt-2 text-slate-600">■ 관리 구분: 집중 돌봄군<br />■ 돌봄 중점: 식사 형태·안전, 영양</p>
          <p className="mt-3 text-navy-600 font-semibold">▶ 돌봄 리포트 보기</p>
        </div>
      </div>
      <p className="mt-4 text-center text-xs text-muted">점수와 어려운 용어 없이, 보호자가 이해할 수 있는 말로 전해집니다.</p>
    </Frame>
  )
}

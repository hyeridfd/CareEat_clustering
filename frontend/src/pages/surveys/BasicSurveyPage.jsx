import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import SurveyLayout from '../../components/layout/SurveyLayout'
import { RadioGroup, SelectField, NumberField, CheckboxGroup, InfoBox, Divider } from '../../components/FormFields'

const TOTAL_PAGES = 10

const DISEASE_OPTIONS = [
  '없음','고혈압','당뇨병','고지혈증','심혈관 질환(심근경색, 협심증, 부정맥 등)',
  '뇌혈관 질환(뇌졸중, 뇌경색, 뇌출혈 등)','갑상선 질환','골다공증','골관절염/류마티스 관절염',
  '암','만성 폐쇄성 폐질환','신장 질환','간 질환','위장 질환','빈혈','치매',
  '파킨슨병','우울증','기타'
]

const MEDICATION_OPTIONS = [
  '복용하지 않음','고혈압약','당뇨병약','고지혈증약','항혈전제','심장약',
  '갑상선약','골다공증약','진통소염제','항암제','천식약',
  '신장약','간약','위장약','철분제','치매약','파킨슨약','항우울제','기타'
]

// K-MBI 항목 설정 (Streamlit과 동일)
const KMBI_OPTIONS_BASE = ['과제를 수행할 수 없는 경우','최대의 도움이 필요한 경우','중등도의 도움이 필요한 경우','최소한의 도움이 필요하거나 감시가 필요한 경우','완전히 독립적인 경우']
const KMBI_OPTIONS_NA = ['해당 사항 없음',...KMBI_OPTIONS_BASE]
const KMBI_ITEMS = [
  { id:'kmbi_1', label:'개인위생', desc:'세수, 머리 빗기, 칫솔질, 면도 등', options:KMBI_OPTIONS_BASE, scores:[0,1,3,4,5] },
  { id:'kmbi_2', label:'목욕하기', desc:'목욕 또는 샤워', options:KMBI_OPTIONS_BASE, scores:[0,1,3,4,5] },
  { id:'kmbi_3', label:'식사하기', desc:'음식을 먹는 동작', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_4', label:'용변처리', desc:'화장실 사용 및 뒤처리', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_5', label:'계단 오르기', desc:'계단 오르고 내리기', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_6', label:'옷 입기', desc:'옷과 신발 착용', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_7', label:'대변조절', desc:'대변 조절 능력', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_8', label:'소변조절', desc:'소변 조절 능력', options:KMBI_OPTIONS_BASE, scores:[0,2,5,8,10] },
  { id:'kmbi_9', label:'보행', desc:'실내외 이동', isWalk:true, options:KMBI_OPTIONS_NA, scores:[0,0,3,8,12,15] },
  { id:'kmbi_10', label:'의자차(휠체어)', desc:'휠체어 사용', isWheelchair:true, options:KMBI_OPTIONS_NA, scores:[0,0,1,3,4,5] },
  { id:'kmbi_11', label:'의자/침대 이동', desc:'의자나 침대로의 이동', options:KMBI_OPTIONS_BASE, scores:[0,3,8,12,15] },
]

// MMSE 카테고리 구조 (Streamlit과 동일)
const MMSE_STRUCTURE = [
  { category: '기억등록', items: [
    { key: 'mmse_reg_airplane', name: '비행기', scores: [0,1] },
    { key: 'mmse_reg_pencil', name: '연필', scores: [0,1] },
    { key: 'mmse_reg_pine', name: '소나무', scores: [0,1] },
  ]},
  { category: '시간지남력', items: [
    { key: 'mmse_time_year', name: '년', scores: [0,1] },
    { key: 'mmse_time_month', name: '월', scores: [0,1] },
    { key: 'mmse_time_day', name: '일', scores: [0,1] },
    { key: 'mmse_time_weekday', name: '요일', scores: [0,1] },
    { key: 'mmse_time_season', name: '계절', scores: [0,1] },
  ]},
  { category: '장소지남력', items: [
    { key: 'mmse_place_country', name: '나라', scores: [0,1] },
    { key: 'mmse_place_city', name: '시/도', scores: [0,1] },
    { key: 'mmse_place_type', name: '무엇하는 곳 또는 구/시·군', scores: [0,1] },
    { key: 'mmse_place_name', name: '현재 장소명', scores: [0,1] },
    { key: 'mmse_place_floor', name: '몇 층 또는 동(도로명)/읍·면', scores: [0,1] },
  ]},
  { category: '기억회상', items: [
    { key: 'mmse_recall_airplane', name: '비행기', scores: [0,1] },
    { key: 'mmse_recall_pencil', name: '연필', scores: [0,1] },
    { key: 'mmse_recall_pine', name: '소나무', scores: [0,1] },
  ]},
  { category: '주의집중 및 계산', items: [
    { key: 'mmse_calc_1', name: '100 - 7', scores: [0,1] },
    { key: 'mmse_calc_2', name: '- 7', scores: [0,1] },
    { key: 'mmse_calc_3', name: '- 7', scores: [0,1] },
    { key: 'mmse_calc_4', name: '- 7', scores: [0,1] },
    { key: 'mmse_calc_5', name: '- 7', scores: [0,1] },
  ]},
  { category: '언어', subcategories: [
    { name: '이름대기', items: [{ key: 'mmse_naming', name: '눈, 귀', scores: [0,1,2] }] },
    { name: '따라 말하기', items: [{ key: 'mmse_repetition', name: '백문이 불여일견', scores: [0,1] }] },
    { name: '이해', items: [{ key: 'mmse_comprehension', name: '동그라미를 가리키고, 네모를 가리킨 다음, 세모를 가리키세요', scores: [0,1,2,3] }] },
    { name: '읽기', items: [{ key: 'mmse_reading', name: '(눈을 감으세요)', scores: [0,1] }] },
    { name: '쓰기', items: [{ key: 'mmse_writing', name: '오늘 날씨를 한 문장으로 써 보세요.', scores: [0,1] }] },
  ]},
  { category: '그리기', items: [
    { key: 'mmse_drawing', name: '오각형', scores: [0,1] },
  ]},
]
// 하위호환용 flat 배열 (점수 계산용)
const MMSE_ITEMS = MMSE_STRUCTURE.flatMap(s =>
  s.items ? s.items : s.subcategories.flatMap(sc => sc.items)
)

export default function BasicSurveyPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/surveys/basic').then(r => { if (r.data && Object.keys(r.data).length > 0) setData(r.data) })
  }, [])

  const update = (fields) => setData(prev => ({ ...prev, ...fields }))

  const handleNext = async () => {
    if (page < TOTAL_PAGES) { setPage(p => p + 1); window.scrollTo(0,0) }
    else await handleSubmit()
  }

  const handleSubmit = async () => {
    setSaving(true)
    try {
      await api.post('/surveys/basic', { data })
      setSaved(true)
      setTimeout(() => navigate('/dashboard'), 1500)
    } catch (e) {
      alert('저장 중 오류가 발생했습니다: ' + (e.response?.data?.detail || e.message))
    } finally { setSaving(false) }
  }

  const goToDashboard = () => navigate('/dashboard')

  const SIDEBAR_ITEMS = [
    { page: 1, label: '인구통계' },
    { page: 2, label: '질환 정보' },
    { page: 3, label: '식사 특성' },
    { page: 4, label: '건강 측정치' },
    { page: 5, label: 'IPAQ-SF' },
    { page: 6, label: 'MNA-SF' },
    { page: 7, label: 'K-MBI' },
    { page: 8, label: 'MMSE-K' },
    { page: 9, label: '시설 특성' },
    { page: 10, label: 'GDS-SF' },
  ]

  if (saved) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="card text-center p-10">
        <div className="text-5xl mb-4">✅</div>
        <p className="text-lg font-semibold text-gray-800">기초 조사표가 저장되었습니다!</p>
        <p className="text-sm text-gray-500 mt-2">대시보드로 이동합니다...</p>
      </div>
    </div>
  )

  const bmi = data.height && data.weight
    ? (data.weight / Math.pow(data.height / 100, 2)).toFixed(1)
    : null

  // 신체활동 MET 계산
  const totalMet = (
    (data.vigorous_activity_days || 0) * (data.vigorous_activity_time || 0) * 8.0 +
    (data.moderate_activity_days || 0) * (data.moderate_activity_time || 0) * 4.0 +
    (data.walking_days || 0) * (data.walking_time || 0) * 3.3
  )
  // Streamlit과 동일한 IPAQ-SF 분류 기준
  const vDays = data.vigorous_activity_days || 0
  const vTime = data.vigorous_activity_time || 0
  const mDays = data.moderate_activity_days || 0
  const wDays = data.walking_days || 0
  const totalVigorousMet = vDays * vTime * 8.0
  const totalModerateMet = (data.moderate_activity_days||0) * (data.moderate_activity_time||0) * 4.0
  const activityLevel =
    (totalMet >= 3000 || (vDays >= 3 && totalVigorousMet >= 1500))
      ? '높은 신체 활동 (High)'
      : (totalMet >= 600 || vDays >= 3 || (mDays + wDays >= 5 && totalModerateMet + (data.walking_days||0)*(data.walking_time||0)*3.3 >= 600))
      ? '중간 수준의 신체 활동 (Moderate)'
      : '낮은 신체 활동 (Low)'

  // K-MBI 점수 (Streamlit과 동일 - 보행/의자차 중 하나만 반영, 인덱스로 저장)
  const getKmbiScore = (itemId) => {
    const item = KMBI_ITEMS.find(i => i.id === itemId)
    if (!item) return 0
    const idx = data[itemId]
    if (idx === undefined || idx === null || idx === '') return 0
    return item.scores[Number(idx)] ?? 0
  }
  const walkScore = getKmbiScore('kmbi_9')
  const wheelScore = getKmbiScore('kmbi_10')
  const baseScore = KMBI_ITEMS.filter(i => i.id !== 'kmbi_9' && i.id !== 'kmbi_10').reduce((s, item) => s + getKmbiScore(item.id), 0)
  const kmbiScore = walkScore > 0 ? baseScore + walkScore : wheelScore > 0 ? baseScore + wheelScore : baseScore
  const kmbiMaxScore = walkScore > 0 ? 100 : wheelScore > 0 ? 90 : 100
  const mobilityType = walkScore > 0 ? '보행' : wheelScore > 0 ? '의자차(휠체어)' : '미선택'
  const kmbiPct = kmbiMaxScore > 0 ? (kmbiScore / kmbiMaxScore * 100) : 0
  const kmbiStatusArr = kmbiPct >= 91 ? ['최소 의존(minimal)', '🟢'] : kmbiPct >= 75 ? ['경도 의존(mild)', '🟡'] : kmbiPct >= 50 ? ['중간 의존(moderate)', '🟠'] : kmbiPct >= 25 ? ['대부분 의존(substantial)', '🔴'] : ['완전 의존(full)', '⚫']
  const [kmbiStatus, kmbiEmoji] = kmbiStatusArr

  // MMSE 점수 (각 항목 최대점수 합산)
  const mmseScore = MMSE_ITEMS.reduce((sum, item) => sum + (Number(data[item.key]) || 0), 0)

  // MNA 점수
  const mnaScore = [
    data.mna_appetite_change, data.mna_weight_change, data.mna_mobility,
    data.mna_stress_illness, data.mna_neuropsychological_problem, data.mna_bmi_category
  ].reduce((s, v) => s + (Number(v) || 0), 0)

  return (
    <SurveyLayout
      title="기초 조사표 (건강설문)"
      icon="📝"
      page={page}
      totalPages={TOTAL_PAGES}
      onPrev={() => { setPage(p => p - 1); window.scrollTo(0,0) }}
      onNext={handleNext}
      onDashboard={goToDashboard}
      nextLabel={saving ? '저장 중...' : undefined}
      sidebarItems={SIDEBAR_ITEMS}
      onPageJump={(p) => { setPage(p); window.scrollTo(0,0) }}
    >
      {/* ── 1페이지: 인구통계 ── */}
      {page === 1 && (
        <div>
          <h2 className="section-title">인구통계학적 특성</h2>
          <RadioGroup label="1. 성별" options={['남자','여자']} value={data.gender} onChange={v => update({gender:v})} horizontal />
          <NumberField label="2. 출생연도" value={data.age} onChange={v => update({age:v})} min={1900} max={2010} />
          <SelectField label="3. 장기요양등급" options={['1등급','2등급','3등급','4등급 이상']} value={data.care_grade} onChange={v => update({care_grade:v})} />
          <SelectField label="4. 요양시설 거주 기간" options={['1년 미만','1년 이상 ~ 3년 미만','3년 이상 ~ 5년 미만','5년 이상 ~ 10년 미만','10년 이상']} value={data.residence_duration} onChange={v => update({residence_duration:v})} />
          <SelectField label="5. 최종 학력" options={['무학','초등학교 졸업','중학교 졸업','고등학교 졸업','대학교(전문대 포함) 졸업 이상']} value={data.education} onChange={v => update({education:v})} />
          <SelectField label="6. 음주 및 흡연 여부" options={['둘 다 안함','과거에 음주를 했음','과거에 흡연을 했음','현재 음주하고 있음','현재 흡연하고 있음','둘 다 하고 있음']} value={data.drinking_smoking} onChange={v => update({drinking_smoking:v})} />
        </div>
      )}

      {/* ── 2페이지: 질환 ── */}
      {page === 2 && (
        <div>
          <h2 className="section-title">질환 정보</h2>
          <CheckboxGroup label="7. 현재 보유 질환 종류 (복수 선택 가능)" options={DISEASE_OPTIONS} value={data.diseases || []} onChange={v => update({diseases:v})} etcValue={data.diseases_etc} onEtcChange={v => update({diseases_etc: v})} />
          <Divider />
          <CheckboxGroup label="8. 현재 복용 중인 약물 (복수 선택 가능)" options={MEDICATION_OPTIONS} value={data.medications || []} onChange={v => update({medications:v})} etcValue={data.medications_etc} onEtcChange={v => update({medications_etc: v})} />
          <SelectField label="9. 약물 복용 개수" options={['없음','1개','2개','3개','4개 이상']} value={data.medication_count} onChange={v => update({medication_count:v})} />
        </div>
      )}

      {/* ── 3페이지: 식사 ── */}
      {page === 3 && (
        <div>
          <h2 className="section-title">식사 관련 특성</h2>
          <RadioGroup label="10. 음식을 씹는 데 어려움이 있습니까?" options={['예','아니오']} value={data.chewing_difficulty === true ? '예' : data.chewing_difficulty === false ? '아니오' : undefined} onChange={v => update({chewing_difficulty: v === '예'})} horizontal />
          <RadioGroup label="11. 음식을 삼키는 데 어려움이 있습니까?" options={['예','아니오']} value={data.swallowing_difficulty === true ? '예' : data.swallowing_difficulty === false ? '아니오' : undefined} onChange={v => update({swallowing_difficulty: v === '예'})} horizontal />
          <SelectField label="12. 평소 식사 방법" options={['스스로 식사할 수 있음','요양보호사 등의 부분적인 도움 필요','요양보호사 등의 전적인 도움 필요']} value={data.eating_independence} onChange={v => update({eating_independence:v})} />
          <SelectField label="13. 식사 형태" options={['일반식','다진식','갈은식(믹서식)','유동식','기타']} value={data.meal_type} onChange={v => update({meal_type:v})} />
          {data.meal_type === '기타' && (
            <input
              type="text"
              className="form-input text-sm mt-1 mb-4"
              placeholder="식사 형태를 직접 입력해주세요"
              value={data.meal_type_etc || ''}
              onChange={e => update({ meal_type_etc: e.target.value })}
            />
          )}
        </div>
      )}

      {/* ── 4페이지: 건강 측정치 ── */}
      {page === 4 && (
        <div>
          <h2 className="section-title">기본 건강 측정치</h2>
          <div className="grid grid-cols-2 gap-4">
            <NumberField label="14. 신장" value={data.height} onChange={v => update({height:v})} unit="cm" min={0} max={250} step={0.1} />
            <NumberField label="15. 체중" value={data.weight} onChange={v => update({weight:v})} unit="kg" min={0} max={200} step={0.1} />
            <NumberField label="16. 수축기 혈압" value={data.systolic_bp} onChange={v => update({systolic_bp:v})} unit="mmHg" min={0} max={300} />
            <NumberField label="17. 이완기 혈압" value={data.diastolic_bp} onChange={v => update({diastolic_bp:v})} unit="mmHg" min={0} max={200} />
            <div>
              {bmi && <InfoBox>BMI: <strong>{bmi}</strong> kg/m²</InfoBox>}
            </div>          
          </div>
        </div>
      )}

      {/* ── 5페이지: IPAQ-SF ── */}
      {page === 5 && (
        <div>
          <h2 className="section-title">신체 활동 수준 조사 (IPAQ-SF)</h2>
          <InfoBox>📝 지난 7일 동안의 신체 활동에 대해 응답해주세요.</InfoBox>

          {/* 1. 격렬한 신체 활동 */}
          <div className="mb-5">
            <p className="font-semibold text-gray-800 mb-1">1. 격렬한 신체 활동</p>
            <p className="text-xs text-gray-400 mb-3">예: 무거운 물건 들기, 땅 파기, 에어로빅, 빠른 속도로 자전거 타기 등</p>
            <div className="grid grid-cols-2 gap-4">
              <NumberField
                label="지난 7일 동안 격렬한 신체 활동을 10분 이상 한 날은 며칠입니까?"
                value={data.vigorous_activity_days}
                onChange={v => update({vigorous_activity_days:v})}
                unit="일" min={0} max={7} />
              <NumberField
                label="그러한 날 중 하루에 보통 얼마나 많은 시간을 격렬한 신체 활동을 하는데 보냈습니까?"
                value={data.vigorous_activity_time}
                onChange={v => update({vigorous_activity_time:v})}
                unit="분" min={0} max={1440} />
            </div>
          </div>

          <Divider />

          {/* 2. 중간 정도 신체 활동 */}
          <div className="mb-5">
            <p className="font-semibold text-gray-800 mb-1">2. 중간 정도의 신체 활동</p>
            <p className="text-xs text-gray-400 mb-3">예: 가벼운 물건 나르기, 보통 속도로 자전거 타기, 복식 테니스 등 (걷기는 제외)</p>
            <div className="grid grid-cols-2 gap-4">
              <NumberField
                label="지난 7일 동안 중간 정도의 신체 활동을 10분 이상 한 날은 며칠입니까?"
                value={data.moderate_activity_days}
                onChange={v => update({moderate_activity_days:v})}
                unit="일" min={0} max={7} />
              <NumberField
                label="그러한 날 중 하루에 보통 얼마나 많은 시간을 중간 정도의 신체 활동을 하는데 보냈습니까?"
                value={data.moderate_activity_time}
                onChange={v => update({moderate_activity_time:v})}
                unit="분" min={0} max={1440} />
            </div>
          </div>

          <Divider />

          {/* 3. 걷기 */}
          <div className="mb-5">
            <p className="font-semibold text-gray-800 mb-1">3. 걷기</p>
            <p className="text-xs text-gray-400 mb-3">직장에서, 집에서, 장소 간 이동, 여가 시간의 모든 걷기를 포함</p>
            <div className="grid grid-cols-2 gap-4">
              <NumberField
                label="지난 7일 동안 10분 이상 걸은 날은 며칠입니까?"
                value={data.walking_days}
                onChange={v => update({walking_days:v})}
                unit="일" min={0} max={7} />
              <NumberField
                label="그러한 날 중 하루에 보통 얼마나 많은 시간을 걷는데 보냈습니까?"
                value={data.walking_time}
                onChange={v => update({walking_time:v})}
                unit="분" min={0} max={1440} />
            </div>
          </div>

          <Divider />

          {/* 4. 앉아서 보낸 시간 */}
          <div className="mb-5">
            <p className="font-semibold text-gray-800 mb-1">4. 앉아서 보낸 시간</p>
            <p className="text-xs text-gray-400 mb-3">책상에 앉아 있거나, 친구를 만나거나, 독서할 때 앉거나, 텔레비전을 앉아서 또는 누워서 시청한 시간이 포함</p>
            <NumberField
              label="지난 7일 동안 평일 하루에 앉아서 보낸 시간은 얼마나 됩니까?"
              value={data.sitting_time}
              onChange={v => update({sitting_time:v})}
              unit="분" min={0} max={1440} />
          </div>

          {/* 활동량 요약 */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mt-2">
            <p className="text-sm font-semibold text-blue-800 mb-3">📊 신체 활동량 요약</p>
            <div className="grid grid-cols-2 gap-2 mb-3">
              {[
                ['격렬한 활동', ((data.vigorous_activity_days||0)*(data.vigorous_activity_time||0)*8.0).toFixed(2)],
                ['중간 활동', ((data.moderate_activity_days||0)*(data.moderate_activity_time||0)*4.0).toFixed(2)],
                ['걷기', ((data.walking_days||0)*(data.walking_time||0)*3.3).toFixed(2)],
                ['총 활동량', totalMet.toFixed(2)],
              ].map(([label, val]) => (
                <div key={label} className="bg-white rounded-lg p-2.5 text-center">
                  <p className="text-xs text-gray-500">{label}</p>
                  <p className="text-sm font-bold text-blue-700 mt-0.5">{val}</p>
                  <p className="text-xs text-gray-400">MET-분/주</p>
                </div>
              ))}
            </div>
            <div className={`rounded-lg px-3 py-2 text-sm font-semibold text-center ${
              activityLevel.includes('높은') ? 'bg-green-100 text-green-800' :
              activityLevel.includes('중간') ? 'bg-yellow-100 text-yellow-800' :
              'bg-red-100 text-red-700'
            }`}>
              💪 신체 활동 수준: {activityLevel}
            </div>
          </div>
        </div>
      )}

      {/* ── 6페이지: MNA-SF ── */}
      {page === 6 && (() => {
        // BMI 자동 계산
        const h = data.height, w = data.weight
        const autoBmi = h && w && h > 0 ? w / Math.pow(h / 100, 2) : null
        let autoBmiScore = null
        let autoBmiLabel = ''
        if (autoBmi) {
          if (autoBmi < 19)       { autoBmiScore = 0; autoBmiLabel = `BMI < 19 (현재: ${autoBmi.toFixed(2)})` }
          else if (autoBmi < 21)  { autoBmiScore = 1; autoBmiLabel = `19 ≤ BMI < 21 (현재: ${autoBmi.toFixed(2)})` }
          else if (autoBmi < 23)  { autoBmiScore = 2; autoBmiLabel = `21 ≤ BMI < 23 (현재: ${autoBmi.toFixed(2)})` }
          else                    { autoBmiScore = 3; autoBmiLabel = `BMI ≥ 23 (현재: ${autoBmi.toFixed(2)})` }
          // BMI 자동 반영
          if (data.mna_bmi_category === undefined || data.mna_bmi_category === null) {
            update({ mna_bmi_category: String(autoBmiScore) })
          }
        }

        // 점수 계산 (Streamlit과 동일)
        const aScore = Number(data.mna_appetite_change ?? 2)
        const wScore = Number(data.mna_weight_change ?? 3)
        const mScore = Number(data.mna_mobility ?? 2)
        const sScore = Number(data.mna_stress_illness ?? 2)
        const nScore = Number(data.mna_neuropsychological_problem ?? 2)
        const bScore = autoBmi !== null ? autoBmiScore : Number(data.mna_bmi_category ?? 3)
        const totalMnaScore = aScore + wScore + mScore + sScore + nScore + bScore

        return (
          <div>
            <h2 className="section-title">영양 상태 평가 (MNA-SF)</h2>
            <InfoBox>📝 간이 영양 평가 (Mini Nutritional Assessment - Short Form)</InfoBox>

            {autoBmi && (
              <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-2.5 mb-4 text-sm text-blue-800">
                📊 기초 조사표 기준 BMI: <strong>{autoBmi.toFixed(2)} kg/m²</strong>
              </div>
            )}

            {/* A */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">A. 지난 3개월 동안 밥맛이 없거나, 소화가 잘 안되거나, 씹고 삼키는 것이 어려워서 식사량이 줄었습니까?</p>
              <RadioGroup label="" options={[
                {value:'0', label:'많이 줄었다'},
                {value:'1', label:'조금 줄었다'},
                {value:'2', label:'변화 없다'},
              ]} value={String(data.mna_appetite_change ?? '')} onChange={v => update({mna_appetite_change: v})} />
            </div>

            {/* B */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">B. 지난 3개월 동안 몸무게가 줄었습니까?</p>
              <RadioGroup label="" options={[
                {value:'0', label:'3kg 이상 감소'},
                {value:'2', label:'1kg~3kg 감소'},
                {value:'3', label:'줄지 않았다'},
                {value:'1', label:'모르겠다'},
              ]} value={String(data.mna_weight_change ?? '')} onChange={v => update({mna_weight_change: v})} />
            </div>

            {/* C */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">C. 거동 능력</p>
              <RadioGroup label="" options={[
                {value:'0', label:'외출할 수 없고, 주로 앉거나 누워서 생활한다'},
                {value:'1', label:'외출할 수는 없지만 집에서는 활동할 수 있다'},
                {value:'2', label:'외출할 수 있다'},
              ]} value={String(data.mna_mobility ?? '')} onChange={v => update({mna_mobility: v})} />
            </div>

            {/* D */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">D. 지난 3개월 동안 많이 괴로운 일이 있었거나, 심하게 편찮으셨던 적이 있습니까?</p>
              <RadioGroup label="" options={[
                {value:'0', label:'예'},
                {value:'2', label:'아니오'},
              ]} value={String(data.mna_stress_illness ?? '')} onChange={v => update({mna_stress_illness: v})} />
            </div>

            {/* E */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">E. 신경 정신과적 문제</p>
              <RadioGroup label="" options={[
                {value:'0', label:'중증 치매나 우울증'},
                {value:'1', label:'경증 치매'},
                {value:'2', label:'없음'},
              ]} value={String(data.mna_neuropsychological_problem ?? '')} onChange={v => update({mna_neuropsychological_problem: v})} />
            </div>

            {/* F - BMI 자동 or 수동 */}
            <div className="mb-5">
              <p className="font-semibold text-gray-800 mb-3">F. 체질량지수 (BMI = kg / m²)</p>
              {autoBmi ? (
                <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 text-sm text-blue-800">
                  📊 자동 산출: <strong>{autoBmiLabel}</strong> → 점수: {autoBmiScore}점
                </div>
              ) : (
                <RadioGroup label="" options={[
                  {value:'0', label:'BMI < 19'},
                  {value:'1', label:'19 ≤ BMI < 21'},
                  {value:'2', label:'21 ≤ BMI < 23'},
                  {value:'3', label:'BMI ≥ 23'},
                ]} value={String(data.mna_bmi_category ?? '')} onChange={v => update({mna_bmi_category: v})} />
              )}
            </div>

            {/* 결과 */}
            <div className="border-t border-gray-200 pt-4 mt-2">
              <p className="text-sm font-semibold text-gray-700 mb-3">📊 MNA-SF 결과</p>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="bg-gray-50 rounded-xl p-3 text-center">
                  <p className="text-xs text-gray-500">총점</p>
                  <p className="text-2xl font-bold text-blue-700 mt-1">{totalMnaScore}<span className="text-sm text-gray-400"> / 14점</span></p>
                </div>
                <div className={`rounded-xl p-3 text-center ${totalMnaScore >= 12 ? 'bg-green-50' : totalMnaScore >= 8 ? 'bg-yellow-50' : 'bg-red-50'}`}>
                  <p className="text-xs text-gray-500">영양 상태</p>
                  <p className={`text-sm font-bold mt-1 ${totalMnaScore >= 12 ? 'text-green-700' : totalMnaScore >= 8 ? 'text-yellow-700' : 'text-red-700'}`}>
                    {totalMnaScore >= 12 ? '정상 영양 상태' : totalMnaScore >= 8 ? '영양불량 위험' : '영양불량'}
                  </p>
                </div>
              </div>
              <div className="bg-gray-50 rounded-xl px-4 py-3 text-xs text-gray-600 leading-relaxed">
                <strong>해석 기준:</strong><br/>
                12~14점: 정상 영양 상태 &nbsp;|&nbsp; 8~11점: 영양불량 위험 &nbsp;|&nbsp; 0~7점: 영양불량
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── 7페이지: K-MBI ── */}
      {page === 7 && (
        <div>
          <h2 className="section-title">K-MBI (한국판 수정 바델 지수)</h2>
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 mb-4 text-sm text-blue-800">
            <p className="font-semibold mb-1">K-MBI 평가 안내</p>
            <p>각 항목에 대해 대상자의 현재 수행 능력을 평가해주세요.</p>
            <p className="mt-1.5 font-medium">⚠️ 보행과 의자차(휠체어)는 둘 중 하나만 선택합니다.<br/>
            보행 가능: 보행 점수 적용 (100점 만점) / 휠체어: 의자차 점수 적용 (90점 만점)</p>
          </div>

          <div className="space-y-4">
            {KMBI_ITEMS.map((item, idx) => {
              const curIdx = data[item.id] !== undefined && data[item.id] !== null && data[item.id] !== ''
                ? Number(data[item.id]) : null
              return (
                <div key={item.id} className="border border-gray-200 rounded-xl p-4">
                  <p className="font-semibold text-gray-800 mb-0.5">{idx+1}. {item.label}</p>
                  <p className="text-xs text-gray-400 mb-3">📌 {item.desc}</p>
                  {(item.isWalk || item.isWheelchair) && (
                    <p className="text-xs text-yellow-700 bg-yellow-50 border border-yellow-200 rounded-lg px-3 py-1.5 mb-3">
                      ⚠️ 보행과 의자차(휠체어) 중 하나만 선택하세요. 다른 하나는 '해당 사항 없음'으로 선택합니다.
                    </p>
                  )}
                  <div className="space-y-2">
                    {item.options.map((opt, optIdx) => {
                      const score = item.scores[optIdx]
                      return (
                        <label key={optIdx} className="flex items-center gap-3 cursor-pointer p-2 rounded-lg hover:bg-gray-50 transition-colors">
                          <input
                            type="radio"
                            name={item.id}
                            checked={curIdx === optIdx}
                            onChange={() => update({ [item.id]: optIdx })}
                            className="accent-blue-600 w-4 h-4 shrink-0"
                          />
                          <span className="text-sm text-gray-700 flex-1">{opt}</span>
                          <span className="text-xs text-blue-600 font-medium shrink-0">{score}점</span>
                        </label>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>

          {/* 결과 */}
          <div className="mt-5 bg-blue-50 border border-blue-200 rounded-xl p-4">
            <p className="text-sm font-semibold text-blue-800 mb-3">📊 K-MBI 평가 결과</p>
            <div className="grid grid-cols-3 gap-2 mb-3">
              <div className="bg-white rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">총점</p>
                <p className="text-xl font-bold text-blue-700 mt-1">{kmbiScore}<span className="text-xs text-gray-400">/{kmbiMaxScore}점</span></p>
              </div>
              <div className="bg-white rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">이동 수단</p>
                <p className="text-sm font-bold text-gray-700 mt-1">{mobilityType}</p>
              </div>
              <div className="bg-white rounded-lg p-3 text-center">
                <p className="text-xs text-gray-500">도움의 수준</p>
                <p className="text-sm font-bold text-gray-700 mt-1">{kmbiEmoji} {kmbiStatus}</p>
              </div>
            </div>
            <div className="bg-white rounded-lg px-4 py-3 text-xs text-gray-600 leading-relaxed">
              <strong>해석 기준:</strong><br/>
              0~24점: 완전 의존 · 25~49점: 대부분 의존 · 50~74점: 중간 의존 · 75~90점: 경도 의존 · 91~99점: 최소 의존<br/>
              <strong className="text-blue-700">현재: {kmbiScore}/{kmbiMaxScore}점 ({kmbiPct.toFixed(1)}%) - {kmbiStatus} / 이동방식: {mobilityType}</strong>
            </div>
          </div>
        </div>
      )}

      {/* ── 8페이지: MMSE ── */}
      {page === 8 && (() => {
        // 교육수준별 정상 기준 (Streamlit과 동일)
        const edu = data.education || ''
        const cutoff = edu.includes('무학') ? 19 : edu.includes('초등') ? 22 : 24
        const mmseStatus = mmseScore >= cutoff ? '정상 인지기능' : mmseScore >= cutoff - 4 ? '경도 인지장애 의심' : '인지장애 의심'
        const mmseStatusColor = mmseScore >= cutoff ? 'bg-green-50 border-green-300 text-green-800' : mmseScore >= cutoff - 4 ? 'bg-yellow-50 border-yellow-300 text-yellow-800' : 'bg-red-50 border-red-300 text-red-800'

        const ScoreBtn = ({ itemKey, score }) => {
          const cur = Number(data[itemKey] ?? -1)
          return (
            <button type="button"
              onClick={() => update({ [itemKey]: score })}
              className={`w-9 h-9 rounded-lg text-sm font-bold border-2 transition-colors ${
                cur === score ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-300 text-gray-600 hover:border-blue-400'
              }`}>{score}</button>
          )
        }

        const ItemRow = ({ item }) => (
          <div className="flex items-center justify-between py-2.5 border-b border-gray-100 last:border-0">
            <span className="text-sm text-gray-700 flex-1 pr-3">{item.name}</span>
            <div className="flex gap-1.5 shrink-0">
              {item.scores.map(s => <ScoreBtn key={s} itemKey={item.key} score={s} />)}
            </div>
          </div>
        )

        return (
          <div>
            <h2 className="section-title">K-MMSE-2 (한국판 간이정신상태검사 2판)</h2>
            <InfoBox>📝 인지기능을 평가합니다. 각 항목의 점수를 클릭하여 선택하세요.</InfoBox>

            {MMSE_STRUCTURE.map(section => (
              <div key={section.category} className="mb-4">
                <h3 className="text-sm font-bold text-gray-800 bg-gray-100 px-3 py-2 rounded-lg mb-1">{section.category}</h3>
                <div className="px-1">
                  {section.items
                    ? section.items.map(item => <ItemRow key={item.key} item={item} />)
                    : section.subcategories.map(sub => (
                        <div key={sub.name} className="mb-2">
                          <p className="text-xs font-semibold text-blue-700 px-1 py-1">{sub.name}</p>
                          {sub.items.map(item => <ItemRow key={item.key} item={item} />)}
                        </div>
                      ))
                  }
                </div>
              </div>
            ))}

            {/* 결과 */}
            <div className="mt-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 text-center">
                  <p className="text-xs text-gray-500">총점</p>
                  <p className="text-2xl font-bold text-blue-700 mt-1">{mmseScore}<span className="text-sm text-gray-400"> / 30점</span></p>
                </div>
                <div className={`border rounded-xl p-3 text-center ${mmseStatusColor}`}>
                  <p className="text-xs opacity-70">판정</p>
                  <p className="text-sm font-bold mt-1">{mmseStatus}</p>
                  <p className="text-xs opacity-70 mt-0.5">기준 ≥{cutoff}점</p>
                </div>
              </div>
              <div className="bg-gray-50 rounded-xl px-4 py-3 text-xs text-gray-600 leading-relaxed">
                <strong>교육 수준별 정상 기준:</strong><br/>
                무학: ≥19점 &nbsp;|&nbsp; 초등학교 졸업: ≥22점 &nbsp;|&nbsp; 중학교 이상: ≥24점
              </div>
              <p className="text-xs text-gray-400 px-1">※ 대체문항: 집/시·동-통/도·방/작·지명/소록 (대체문항에 관한 자세한 내용은 사용자 지침서를 참고하시기 바랍니다.)</p>
            </div>
          </div>
        )
      })()}

      {/* ── 9페이지: 시설 특성 ── */}
      {page === 9 && (
        <div>
          <h2 className="section-title">시설 특성</h2>
          <NumberField label="시설 정원 (명)" value={data.facility_capacity} onChange={v => update({facility_capacity:v})} min={0} />
          <SelectField label="시설 소재지" options={['서울','부산','대구','인천','광주','대전','울산','세종','경기','강원','충북','충남','전북','전남','경북','경남','제주']} value={data.facility_location} onChange={v => update({facility_location:v})} />
          <RadioGroup label="영양사 배치 여부" options={['예','아니오']} value={data.nutritionist_present === true ? '예' : data.nutritionist_present === false ? '아니오' : undefined} onChange={v => update({nutritionist_present: v === '예'})} horizontal />
        </div>
      )}

      {/* ── 10페이지: GDS-SF (우울 척도) ── */}
      {page === 10 && (() => {
        // GDS-SF 15문항
        // 역채점 문항 (아니오=1점): 1, 5, 7, 11, 13번
        const GDS_ITEMS = [
          { key: 'gds_1',  q: '1. 본인의 삶에 대체로 만족하십니까?',              reverse: true  },
          { key: 'gds_2',  q: '2. 최근에 활동이나 관심거리가 줄었습니까?',        reverse: false },
          { key: 'gds_3',  q: '3. 삶이 공허하다고 느끼십니까?',                   reverse: false },
          { key: 'gds_4',  q: '4. 자주 싫증을 느끼십니까?',                       reverse: false },
          { key: 'gds_5',  q: '5. 기분좋게 사시는 편입니까?',                     reverse: true  },
          { key: 'gds_6',  q: '6. 좋지 않은 일이 닥쳐올까 두렵습니까?',           reverse: false },
          { key: 'gds_7',  q: '7. 대체로 행복하다고 느끼십니까?',                 reverse: true  },
          { key: 'gds_8',  q: '8. 자주 무기력함을 느끼십니까?',                   reverse: false },
          { key: 'gds_9',  q: '9. 외출보다는 집안에 있기를 좋아하십니까?',        reverse: false },
          { key: 'gds_10', q: '10. 다른 사람들보다 기억력이 떨어진다고 느끼십니까?', reverse: false },
          { key: 'gds_11', q: '11. 살아있다는 사실이 기쁘십니까?',                reverse: true  },
          { key: 'gds_12', q: '12. 본인의 삶이 가치가 없다고 느끼십니까?',        reverse: false },
          { key: 'gds_13', q: '13. 생활에 활력이 넘치십니까?',                    reverse: true  },
          { key: 'gds_14', q: '14. 본인의 현실이 절망적이라고 느끼십니까?',       reverse: false },
          { key: 'gds_15', q: '15. 다른 사람들이 대체로 본인보다 낫다고 느끼십니까?', reverse: false },
        ]

        // 점수 계산: 역채점 문항은 '아니오'=1, 일반 문항은 '예'=1
        const gdsScore = GDS_ITEMS.reduce((sum, item) => {
          const val = data[item.key]
          if (val === undefined || val === null) return sum
          const score = item.reverse ? (val === '아니오' ? 1 : 0) : (val === '예' ? 1 : 0)
          return sum + score
        }, 0)

        const answeredCount = GDS_ITEMS.filter(item => data[item.key] !== undefined && data[item.key] !== null).length

        const gdsStatus = gdsScore <= 5 ? '정상' : gdsScore <= 9 ? '가벼운 우울증' : '심한 우울증'
        const gdsColor = gdsScore <= 5 ? 'bg-green-50 border-green-300 text-green-800' : gdsScore <= 9 ? 'bg-yellow-50 border-yellow-300 text-yellow-800' : 'bg-red-50 border-red-300 text-red-800'

        return (
          <div>
            <h2 className="section-title">우울 척도 (GDS-SF)</h2>
            <InfoBox>📝 현재의 상태에 해당하는 답에 예/아니오로 응답해주세요. (총 15문항)</InfoBox>
            <div className="space-y-1">
              {GDS_ITEMS.map((item) => {
                const val = data[item.key]
                return (
                  <div key={item.key} className="flex items-center justify-between py-3 border-b border-gray-100 last:border-0">
                    <span className="text-sm text-gray-700 flex-1 pr-4">{item.q}</span>
                    <div className="flex gap-2 shrink-0">
                      {['예', '아니오'].map(opt => (
                        <button
                          key={opt}
                          type="button"
                          onClick={() => update({ [item.key]: opt })}
                          className={`px-3 py-1.5 rounded-lg text-sm font-medium border-2 transition-colors ${
                            val === opt
                              ? 'bg-blue-600 border-blue-600 text-white'
                              : 'bg-white border-gray-300 text-gray-600 hover:border-blue-400'
                          }`}
                        >{opt}</button>
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>

            {/* 결과 */}
            <div className="mt-5 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-blue-50 border border-blue-200 rounded-xl p-3 text-center">
                  <p className="text-xs text-gray-500">총점 ({answeredCount}/15 응답)</p>
                  <p className="text-2xl font-bold text-blue-700 mt-1">{gdsScore}<span className="text-sm text-gray-400"> / 15점</span></p>
                </div>
                <div className={`border rounded-xl p-3 text-center ${gdsColor}`}>
                  <p className="text-xs opacity-70">판정</p>
                  <p className="text-sm font-bold mt-1">{gdsStatus}</p>
                </div>
              </div>
              <div className="bg-gray-50 rounded-xl px-4 py-3 text-xs text-gray-600 leading-relaxed">
                <strong>해석 기준:</strong><br/>
                0~5점: 정상 &nbsp;|&nbsp; 6~9점: 가벼운 우울증 &nbsp;|&nbsp; 10~15점: 심한 우울증
              </div>
              <p className="text-xs text-gray-400 px-1">※ 음영처리=1점, 비음영처리=0점</p>
            </div>
          </div>
        )
      })()}
    </SurveyLayout>
  )
}
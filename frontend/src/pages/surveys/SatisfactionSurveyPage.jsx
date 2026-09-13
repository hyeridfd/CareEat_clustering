import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import SurveyLayout from '../../components/layout/SurveyLayout'
import { RadioGroup, CheckboxGroup, InfoBox, Divider, ScaleRating } from '../../components/FormFields'

const TOTAL_PAGES = 2

const SCALE_LABELS_SATISFACTION = ['매우 불만족', '불만족', '보통', '만족', '매우 만족']
const SCALE_LABELS_AMOUNT = ['매우 부족', '부족', '적당', '많음', '매우 많음']
const SCALE_LABELS_EASE = ['매우 어려움', '어려움', '보통', '쉬움', '매우 쉬움']
const SCALE_LABELS_REPURCHASE = ['매우 낮음', '낮음', '보통', '높음', '매우 높음']

const FOOD_GROUPS = ['밥·죽류','국·찌개류','고기류','생선·해산물류','채소·나물류','두부·콩류','채소류','과일','기타']
const COOKING_METHODS = ['찌기','삶기','굽기','볶기','튀기기','조림','무침','국/탕/찌개','생식 (회, 샐러드 등)']
const SEAFOOD_TYPES = ['고등어','갈치','명태/동태','조기','삼치','참치','오징어','낙지','새우','조개류','기타']
const COOKING_TYPES = ['구이','조림','찌개/국','볶음','튀김','회/생식','무침','기타']

function ScaleQuestion({ label, value, onChange, labels }) {
  return (
    <div className="mb-5">
      <p className="text-sm font-medium text-gray-700 mb-2">{label}</p>
      <div className="flex gap-2">
        {[1,2,3,4,5].map(n => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`flex-1 py-2 rounded-lg text-xs font-medium border-2 transition-colors ${
              value === n
                ? 'bg-blue-600 border-blue-600 text-white'
                : 'bg-white border-gray-200 text-gray-600 hover:border-blue-300'
            }`}
          >
            {n}<br/><span className="text-xs">{labels[n-1]}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

export default function SatisfactionSurveyPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api.get('/surveys/satisfaction').then(r => {
      const d = r.data
      if (d && Object.keys(d).length > 0) {
        // JSON 파싱
        const parsed = { ...d }
        for (const f of ['preferred_food_groups','preferred_cooking_methods','bluefood_preferences','desired_cooking_types','desired_seafood_types']) {
          if (parsed[f] && typeof parsed[f] === 'string') {
            try { parsed[f] = JSON.parse(parsed[f]) } catch {}
          }
        }
        setData(parsed)
      }
    })
  }, [])

  const update = (fields) => setData(prev => ({ ...prev, ...fields }))

  const handleNext = async () => {
    if (page < TOTAL_PAGES) { setPage(p => p + 1); window.scrollTo(0,0) }
    else await handleSubmit()
  }

  const handleSubmit = async () => {
    setSaving(true)
    try {
      await api.post('/surveys/satisfaction', { data })
      setSaved(true)
      setTimeout(() => navigate('/dashboard'), 1500)
    } catch (e) {
      alert('저장 중 오류: ' + (e.response?.data?.detail || e.message))
    } finally { setSaving(false) }
  }

  if (saved) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="card text-center p-10">
        <div className="text-5xl mb-4">✅</div>
        <p className="text-lg font-semibold">만족도 조사표가 저장되었습니다!</p>
        <p className="text-sm text-gray-500 mt-2">대시보드로 이동합니다...</p>
      </div>
    </div>
  )

  return (
    <SurveyLayout
      title="만족도 및 선호도 조사표"
      icon="😊"
      page={page}
      totalPages={TOTAL_PAGES}
      onPrev={() => { setPage(p => p - 1); window.scrollTo(0,0) }}
      onNext={handleNext}
      onDashboard={() => navigate('/dashboard')}
      nextLabel={saving ? '저장 중...' : undefined}
    >
      {/* ── 1페이지: 급식 만족도 ── */}
      {page === 1 && (
        <div>
          <h2 className="section-title">급식 만족도</h2>
          <InfoBox>현재 제공받는 급식에 대한 만족도를 1~5점으로 평가해주세요.</InfoBox>

          <ScaleQuestion
            label="1. 현재 시설에서 제공되는 급식에 전반적으로 얼마나 만족하십니까?"
            value={data.overall_satisfaction}
            onChange={v => update({ overall_satisfaction: v })}
            labels={SCALE_LABELS_SATISFACTION}
          />
          <ScaleQuestion
            label="2. 제공되는 급식의 양은 적절합니까?"
            value={data.portion_adequacy}
            onChange={v => update({ portion_adequacy: v })}
            labels={SCALE_LABELS_AMOUNT}
          />
          <ScaleQuestion
            label="3. 급식의 맛과 품질에 만족하십니까?"
            value={data.food_quality}
            onChange={v => update({ food_quality: v })}
            labels={SCALE_LABELS_SATISFACTION}
          />

          {(data.overall_satisfaction || data.portion_adequacy || data.food_quality) && (
            <div className="grid grid-cols-3 gap-3 mt-4">
              {[
                ['전반적 만족도', data.overall_satisfaction],
                ['양의 적절성', data.portion_adequacy],
                ['품질 만족도', data.food_quality],
              ].map(([l, v]) => (
                <div key={l} className="text-center bg-blue-50 rounded-lg p-2">
                  <p className="text-xs text-gray-500">{l}</p>
                  <p className="text-lg font-bold text-blue-600">{v || '-'}<span className="text-xs text-gray-400">/5</span></p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── 2페이지: 식품 선호도 ── */}
      {page === 2 && (
        <div>
          <h2 className="section-title">식품 선호도</h2>
          <CheckboxGroup
            label="1. 선호하는 식품군 (복수 선택 가능)"
            options={FOOD_GROUPS}
            value={data.preferred_food_groups || []}
            onChange={v => update({ preferred_food_groups: v })}
          />
          <Divider />
          <CheckboxGroup
            label="2. 선호하는 조리 방법 (복수 선택 가능)"
            options={COOKING_METHODS}
            value={data.preferred_cooking_methods || []}
            onChange={v => update({ preferred_cooking_methods: v })}
          />
          <Divider />
          <div className="mb-4">
            <label className="question-label">3. 급식 개선 사항 (자유롭게 작성)</label>
            <textarea
              className="form-input min-h-24 resize-none"
              value={data.improvement_suggestions || ''}
              onChange={e => update({ improvement_suggestions: e.target.value })}
              placeholder="개선되었으면 하는 점을 자유롭게 작성해주세요."
            />
          </div>
        </div>
      )}
    </SurveyLayout>
  )
}

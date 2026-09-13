import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import SurveyLayout from '../../components/layout/SurveyLayout'
import { InfoBox } from '../../components/FormFields'

// ── 수산물/메뉴 데이터 ──
const MENU_DATA = {
  '맛살': { '밥/죽': ['게맛살볶음밥'], '무침': ['게맛살콩나물무침'], '볶음': ['맛살볶음'], '부침': ['맛살전'] },
  '어란': { '밥/죽': ['날치알밥'], '면류': ['명란파스타'], '국/탕': ['알탕'], '찜': ['날치알달걀찜'], '무침': ['명란젓갈'], '볶음': ['날치알스크램블에그'], '부침': ['날치알계란말이'], '구이': ['명란구이'] },
  '어묵': { '밥/죽': ['어묵볶음밥'], '면류': ['어묵우동'], '국/탕': ['어묵탕'], '조림': ['어묵조림'], '찜': ['콩나물어묵찜','어묵찜'], '볶음': ['매콤어묵볶음','간장어묵볶음'], '부침': ['어묵전'], '튀김': ['어묵고로케'] },
  '쥐포': { '조림': ['쥐포조림'], '무침': ['쥐포무침'], '볶음': ['쥐포볶음'], '부침': ['쥐포전'], '튀김': ['쥐포튀김'], '구이': ['쥐포구이'] },
  '김': { '밥/죽': ['김밥'], '무침': ['김무침'], '튀김': ['김부각'], '구이': ['김자반'] },
  '다시마': { '무침': ['다시마채무침'], '볶음': ['다시마채볶음'], '튀김': ['다시마튀각'] },
  '매생이': { '면류': ['매생이칼국수'], '국/탕': ['매생이굴국'], '부침': ['매생이전'] },
  '미역': { '밥/죽': ['미역국밥'], '국/탕': ['미역국'], '무침': ['미역초무침'], '볶음': ['미역줄기볶음'] },
  '파래': { '무침': ['파래무침'], '볶음': ['파래볶음'], '부침': ['물파래전'] },
  '톳': { '밥/죽': ['톳밥'], '무침': ['톳무침'] },
  '꼴뚜기': { '조림': ['꼴뚜기조림'], '찜': ['꼴뚜기찜'], '무침': ['꼴뚜기젓무침'], '볶음': ['꼴뚜기볶음'] },
  '낙지': { '밥/죽': ['낙지비빔밥'], '면류': ['낙지수제비'], '국/탕': ['낙지연포탕'], '찜': ['낙지찜'], '무침': ['낙지초무침'], '볶음': ['낙지볶음'], '구이': ['낙지호롱구이'], '기타': ['낙지탕탕이'] },
  '문어': { '밥/죽': ['문어볶음밥'], '면류': ['문어라면'], '국/탕': ['문어탕'], '조림': ['문어조림'], '찜': ['문어콩나물찜'], '무침': ['문어초무침'], '볶음': ['문어볶음'], '부침': ['문어전'], '튀김': ['문어튀김'], '기타': ['문어회'] },
  '오징어': { '밥/죽': ['오징어덮밥'], '국/탕': ['오징어무국'], '조림': ['오징어조림'], '찜': ['오징어콩나물찜','오징어숙회'], '무침': ['오징어초무침'], '볶음': ['오징어볶음'], '부침': ['오징어해물전'], '튀김': ['오징어튀김'], '구이': ['오징어버터구이'], '기타': ['오징어회'] },
  '주꾸미': { '밥/죽': ['주꾸미볶음덮밥'], '면류': ['주꾸미감자수제비','주꾸미짬뽕'], '국/탕': ['주꾸미연포탕'], '찜': ['주꾸미숙회','주꾸미찜'], '무침': ['주꾸미무침'], '볶음': ['주꾸미볶음'] },
  '가재': { '찜': ['가재찜'], '구이': ['가재구이'] },
  '게': { '밥/죽': ['게살볶음밥'], '면류': ['게살파스타','꽃게라면'], '국/탕': ['꽃게탕'], '조림': ['꽃게조림'], '찜': ['꽃게찜'], '무침': ['꽃게무침'], '볶음': ['꽃게볶음'], '튀김': ['꽃게강정'], '기타': ['간장게장','양념게장'] },
  '새우': { '밥/죽': ['새우볶음밥'], '면류': ['새우크림파스타'], '국/탕': ['새우달걀국','얼큰새우매운탕'], '조림': ['새우조림'], '찜': ['새우달걀찜'], '무침': ['새우젓'], '볶음': ['건새우볶음'], '부침': ['새우전'], '튀김': ['새우튀김'], '구이': ['새우버터구이'], '기타': ['간장새우장','양념새우장'] },
  '다슬기': { '면류': ['다슬기수제비'], '국/탕': ['다슬기된장국'], '무침': ['다슬기무침'], '부침': ['다슬기파전'] },
  '꼬막': { '밥/죽': ['꼬막비빔밥'], '면류': ['꼬막칼국수'], '국/탕': ['꼬막된장찌개'], '찜': ['꼬막찜'], '무침': ['꼬막무침'], '부침': ['꼬막전'], '구이': ['꼬막떡꼬치구이'] },
  '가리비': { '밥/죽': ['가리비초밥'], '면류': ['가리비칼국수'], '국/탕': ['가리비탕'], '찜': ['가리비찜'], '무침': ['가리비초무침'], '볶음': ['가리비볶음'], '구이': ['가리비버터구이'] },
  '골뱅이': { '밥/죽': ['골뱅이죽'], '면류': ['골뱅이비빔면'], '국/탕': ['골뱅이탕'], '무침': ['골뱅이무침'], '볶음': ['골뱅이볶음'], '튀김': ['골뱅이튀김'], '구이': ['골뱅이꼬치구이'], '기타': ['골뱅이물회'] },
  '굴': { '밥/죽': ['굴국밥'], '면류': ['굴칼국수','굴짬뽕'], '국/탕': ['매생이굴국','굴순두부찌개'], '조림': ['굴조림'], '찜': ['굴찜'], '무침': ['굴무침'], '볶음': ['굴볶음'], '부침': ['굴전'], '튀김': ['굴튀김'], '구이': ['굴구이'], '기타': ['생굴'] },
  '미더덕': { '밥/죽': ['미더덕밥'], '국/탕': ['미더덕된장찌개','미더덕순두부찌개'], '찜': ['미더덕콩나물찜'] },
  '바지락': { '밥/죽': ['바지락비빔밥'], '면류': ['바지락칼국수'], '국/탕': ['바지락미역국','바지락순두부찌개'], '찜': ['바지락찜'], '무침': ['바지락무침'], '볶음': ['바지락볶음','매콤바지락볶음'], '부침': ['바지락부추전'] },
  '백합': { '밥/죽': ['백합볶음밥'], '면류': ['백합칼국수'], '국/탕': ['백합탕'], '찜': ['백합찜'], '무침': ['백합무침'], '볶음': ['백합볶음'], '구이': ['백합구이'] },
  '소라': { '밥/죽': ['참소라야채죽'], '면류': ['소라비빔면'], '국/탕': ['소라된장찌개'], '조림': ['참소라장조림'], '찜': ['소라숙회'], '무침': ['소라무침'], '볶음': ['소라버터볶음'], '튀김': ['소라튀김'], '구이': ['소라구이'], '기타': ['소라회'] },
  '재첩': { '국/탕': ['재첩국'], '무침': ['재첩무침'], '부침': ['재첩부추전'] },
  '전복': { '밥/죽': ['전복죽'], '면류': ['전복파스타'], '국/탕': ['전복미역국'], '조림': ['전복장조림'], '찜': ['전복찜'], '무침': ['전복무침'], '볶음': ['전복볶음'], '구이': ['전복구이'], '기타': ['전복회'] },
  '홍합': { '밥/죽': ['홍합죽'], '면류': ['홍합칼국수','홍합짬뽕'], '국/탕': ['홍합탕','홍합된장찌개'], '조림': ['홍합조림'], '찜': ['홍합찜'], '무침': ['홍합무침'], '볶음': ['홍합볶음'], '부침': ['홍합전'], '구이': ['홍합구이'] },
  '가자미': { '국/탕': ['가자미미역국'], '조림': ['가자미조림'], '찜': ['가자미찜'], '부침': ['가자미전'], '튀김': ['가자미튀김'], '구이': ['가자미구이'] },
  '다랑어': { '밥/죽': ['참치김밥'], '국/탕': ['참치김치찌개'], '볶음': ['참치양배추볶음'], '부침': ['참치달걀말이'], '구이': ['참치스테이크'], '기타': ['참치회'] },
  '고등어': { '조림': ['고등어조림'], '구이': ['고등어구이'] },
  '갈치': { '조림': ['갈치조림'], '구이': ['갈치구이'] },
  '꽁치': { '국/탕': ['꽁치김치찌개'], '조림': ['꽁치조림'], '구이': ['꽁치구이'] },
  '대구': { '국/탕': ['맑은대구탕','대구매운탕'], '조림': ['대구조림'], '부침': ['대구전'] },
  '멸치': { '밥/죽': ['멸치김밥'], '볶음': ['멸치볶음'] },
  '명태': { '국/탕': ['황태미역국'], '조림': ['코다리조림'], '찜': ['명태찜'], '무침': ['북어채무침'], '구이': ['코다리구이'] },
  '박대': { '조림': ['박대조림'], '구이': ['박대구이'] },
  '뱅어': { '무침': ['뱅어포무침'], '튀김': ['뱅어포튀김'] },
  '병어': { '조림': ['병어조림'], '구이': ['병어구이'] },
  '삼치': { '조림': ['삼치조림'], '튀김': ['삼치튀김'], '구이': ['삼치구이'] },
  '아귀': { '국/탕': ['아귀탕'], '찜': ['아귀찜'] },
  '연어': { '밥/죽': ['연어덮밥'], '구이': ['연어구이'], '기타': ['연어회'] },
  '임연수': { '조림': ['임연수조림'], '구이': ['임연수구이'] },
  '장어': { '밥/죽': ['장어덮밥'], '조림': ['장어조림'], '찜': ['장어찜'], '튀김': ['장어튀김'], '구이': ['장어구이'] },
  '조기': { '조림': ['조기조림'], '찜': ['조기찜'], '구이': ['조기구이'] },
}

const CATEGORIES = [
  { label: '🍤 가공수산물', items: ['맛살', '어란', '어묵', '쥐포'] },
  { label: '🌿 해조류', items: ['김', '다시마', '매생이', '미역', '파래', '톳'] },
  { label: '🦑 연체류', items: ['꼴뚜기', '낙지', '문어', '오징어', '주꾸미'] },
  { label: '🦀 갑각류', items: ['가재', '게', '새우'] },
  { label: '🐚 패류', items: ['다슬기', '꼬막', '가리비', '골뱅이', '굴', '미더덕', '바지락', '백합', '소라', '재첩', '전복', '홍합'] },
  { label: '🐟 어류', items: ['가자미', '다랑어', '고등어', '갈치', '꽁치', '대구', '멸치', '명태', '박대', '뱅어', '병어', '삼치', '아귀', '연어', '임연수', '장어', '조기'] },
]

const getAllMenus = (ingredient) => {
  const data = MENU_DATA[ingredient] || {}
  return Object.values(data).flat()
}

export default function BluefoodSurveyPage() {
  const navigate = useNavigate()
  const [catIdx, setCatIdx] = useState(0)           // 현재 카테고리 인덱스
  const [step, setStep] = useState('guide')          // guide → category → complete
  const [selectedIngredients, setSelectedIngredients] = useState([])
  const [selectedMenus, setSelectedMenus] = useState({})  // { 재료: [메뉴, ...] }
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const toggleIngredient = (name) => {
    setSelectedIngredients(prev =>
      prev.includes(name) ? prev.filter(i => i !== name) : [...prev, name]
    )
    if (selectedIngredients.includes(name)) {
      setSelectedMenus(prev => { const n = {...prev}; delete n[name]; return n })
    } else {
      setSelectedMenus(prev => ({ ...prev, [name]: prev[name] || [] }))
    }
  }

  const toggleMenu = (ingredient, menu) => {
    setSelectedMenus(prev => {
      const cur = prev[ingredient] || []
      return {
        ...prev,
        [ingredient]: cur.includes(menu) ? cur.filter(m => m !== menu) : [...cur, menu]
      }
    })
  }

  const currentCat = CATEGORIES[catIdx]
  const chosenInThisCat = currentCat.items.filter(i => selectedIngredients.includes(i))
  const allMenusValid = chosenInThisCat.every(i => (selectedMenus[i]?.length || 0) > 0)
  const isLastCat = catIdx === CATEGORIES.length - 1
  const canProceed = allMenusValid && (isLastCat ? selectedIngredients.length >= 3 : true)

  const handleSubmit = async () => {
    setSaving(true)
    try {
      await api.post('/surveys/bluefood', {
        data: {
          selected_ingredients: selectedIngredients,
          selected_menus: selectedMenus,
        }
      })
      setSaved(true)
      setTimeout(() => navigate('/dashboard'), 1500)
    } catch (e) {
      alert('저장 중 오류: ' + (e.response?.data?.detail || e.message))
    } finally { setSaving(false) }
  }

  // 기존 응답 불러오기
  useEffect(() => {
    api.get('/surveys/bluefood').then(r => {
      const d = r.data
      if (d && Object.keys(d).length > 0) {
        try {
          if (d.selected_ingredients) setSelectedIngredients(typeof d.selected_ingredients === 'string' ? JSON.parse(d.selected_ingredients) : d.selected_ingredients)
          if (d.selected_menus) setSelectedMenus(typeof d.selected_menus === 'string' ? JSON.parse(d.selected_menus) : d.selected_menus)
        } catch {}
      }
    })
  }, [])

  if (saved) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="card text-center p-10">
        <div className="text-5xl mb-4">✅</div>
        <p className="text-lg font-semibold">블루푸드 선호도 조사가 저장되었습니다!</p>
        <p className="text-sm text-gray-500 mt-2">대시보드로 이동합니다...</p>
      </div>
    </div>
  )

  // ── 안내 화면 ──
  if (step === 'guide') return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm px-4 py-3 flex items-center gap-3">
        <button onClick={() => navigate('/dashboard')} className="text-gray-400 hover:text-gray-700 text-xl">←</button>
        <h1 className="text-base font-bold text-gray-900">🐟 블루푸드 선호도 조사</h1>
      </header>
      <div className="max-w-2xl mx-auto p-4 space-y-4">
        <div className="card">
          <h2 className="text-xl font-bold text-gray-800 mb-4">설문 안내</h2>
          <div className="space-y-3">
            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4">
              <p className="font-semibold text-blue-800 mb-1">1단계</p>
              <p className="text-sm text-blue-700">카테고리별로 <strong>좋아하는 수산물</strong>을 모두 선택해주세요.</p>
            </div>
            <div className="bg-purple-50 border border-purple-200 rounded-xl p-4">
              <p className="font-semibold text-purple-800 mb-1">2단계</p>
              <p className="text-sm text-purple-700">선택한 수산물마다 <strong>선호하는 메뉴</strong>를 1개 이상 선택해주세요.</p>
            </div>
            <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4">
              <p className="text-sm font-semibold text-yellow-800">⚠️ 전체 설문 기준으로 최소 <strong>3개 이상</strong> 수산물을 선택해주세요.</p>
            </div>
          </div>
        </div>
        <button onClick={() => setStep('category')} className="btn-primary w-full py-4 text-lg">
          🚀 설문 시작하기
        </button>
      </div>
    </div>
  )

  // ── 카테고리별 선택 화면 ──
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm px-4 py-3 flex items-center gap-3">
        <button onClick={() => { catIdx === 0 ? setStep('guide') : setCatIdx(i => i-1) }} className="text-gray-400 hover:text-gray-700 text-xl">←</button>
        <div className="flex-1">
          <h1 className="text-base font-bold text-gray-900">🐟 블루푸드 선호도 조사</h1>
          <p className="text-xs text-gray-400">{catIdx + 1} / {CATEGORIES.length} — {currentCat.label}</p>
        </div>
      </header>

      {/* 진행 바 */}
      <div className="w-full bg-gray-200 h-1.5">
        <div className="bg-blue-600 h-1.5 transition-all duration-300" style={{ width: `${((catIdx + 1) / CATEGORIES.length) * 100}%` }} />
      </div>

      <div className="max-w-2xl mx-auto p-4 space-y-4">
        {/* 전체 선택 수 */}
        <div className={`rounded-xl px-4 py-2 text-sm font-medium ${selectedIngredients.length >= 3 ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-yellow-50 text-yellow-700 border border-yellow-200'}`}>
          전체 선택 수산물: <strong>{selectedIngredients.length}개</strong>
          {selectedIngredients.length < 3 && ' (최소 3개 이상 선택)'}
        </div>

        {/* 수산물 선택 */}
        <div className="card">
          <h2 className="section-title">{currentCat.label} — 수산물 선택</h2>
          <p className="text-xs text-gray-500 mb-3">좋아하는 수산물을 모두 선택해주세요. 없으면 선택하지 않아도 됩니다.</p>
          <div className="grid grid-cols-3 gap-2">
            {currentCat.items.map(name => {
              const selected = selectedIngredients.includes(name)
              return (
                <button key={name} type="button"
                  onClick={() => toggleIngredient(name)}
                  className={`py-3 px-2 rounded-xl text-sm font-medium border-2 transition-colors ${
                    selected ? 'bg-blue-600 border-blue-600 text-white' : 'bg-white border-gray-200 text-gray-700 hover:border-blue-300'
                  }`}>
                  {selected && '👍 '}{name}
                </button>
              )
            })}
          </div>
        </div>

        {/* 메뉴 선택 */}
        {chosenInThisCat.length > 0 && (
          <div className="card">
            <h2 className="section-title">🍽️ 메뉴 선택</h2>
            <p className="text-xs text-gray-500 mb-3">각 수산물마다 최소 1개 이상의 메뉴를 선택해주세요.</p>
            <div className="space-y-5">
              {chosenInThisCat.map(ingredient => {
                const menus = getAllMenus(ingredient)
                const chosen = selectedMenus[ingredient] || []
                const valid = chosen.length > 0
                return (
                  <div key={ingredient}>
                    <div className="flex items-center gap-2 mb-2">
                      <h3 className="text-sm font-bold text-gray-800">{ingredient}</h3>
                      {valid
                        ? <span className="text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full">✅ {chosen.length}개 선택</span>
                        : <span className="text-xs text-red-500 bg-red-50 px-2 py-0.5 rounded-full">최소 1개 선택 필요</span>
                      }
                    </div>
                    <div className="grid grid-cols-3 gap-1.5">
                      {menus.map(menu => {
                        const sel = chosen.includes(menu)
                        return (
                          <button key={menu} type="button"
                            onClick={() => toggleMenu(ingredient, menu)}
                            className={`py-2 px-1 rounded-lg text-xs font-medium border-2 transition-colors ${
                              sel ? 'bg-purple-600 border-purple-600 text-white' : 'bg-white border-gray-200 text-gray-600 hover:border-purple-300'
                            }`}>
                            {sel && '👍 '}{menu}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )}

        {/* 선택 요약 */}
        {chosenInThisCat.length > 0 && (
          <div className="card bg-gray-50">
            <p className="text-xs font-semibold text-gray-500 mb-2">이번 카테고리 선택 요약</p>
            {chosenInThisCat.map(ing => (
              <div key={ing} className="text-xs text-gray-700 mb-1">
                <strong>{ing}</strong>: {(selectedMenus[ing] || []).join(', ') || '(메뉴 미선택)'}
              </div>
            ))}
          </div>
        )}

        {/* 네비게이션 */}
        <div className="flex gap-3">
          <button onClick={() => navigate('/dashboard')} className="btn-secondary px-4">🏠</button>
          {catIdx > 0 && (
            <button onClick={() => { setCatIdx(i => i-1); window.scrollTo(0,0) }} className="btn-secondary flex-1">← 이전</button>
          )}
          {isLastCat ? (
            <button
              onClick={handleSubmit}
              disabled={!canProceed || saving}
              className="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed">
              {saving ? '저장 중...' : '✅ 제출'}
            </button>
          ) : (
            <button
              onClick={() => { setCatIdx(i => i+1); window.scrollTo(0,0) }}
              disabled={!allMenusValid}
              className="btn-primary flex-1 disabled:opacity-50 disabled:cursor-not-allowed">
              다음 →
            </button>
          )}
        </div>

        {isLastCat && selectedIngredients.length < 3 && (
          <p className="text-xs text-red-500 text-center">⚠️ 최소 3개 이상 수산물을 선택해야 제출할 수 있습니다.</p>
        )}
      </div>
    </div>
  )
}
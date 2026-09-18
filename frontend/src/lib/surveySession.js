// 담당자가 어르신 조사를 직접 입력할 때 쓰는 임시 세션
// 창(탭)마다 따로 두어, 다른 창의 담당자 로그인에 영향을 주지 않는다.
const TOKEN = 'surveyToken'
const TARGET = 'surveyTarget'

const store = () => {
  try { return window.sessionStorage } catch { return null }
}

export function startSurvey({ token, elderly_id, display_name }) {
  const s = store()
  if (!s) return
  s.setItem(TOKEN, token)
  s.setItem(TARGET, JSON.stringify({ elderly_id, display_name }))
}

export function getSurveyTarget() {
  const s = store()
  if (!s) return null
  try {
    const token = getSurveyToken()
    const raw = s.getItem(TARGET)
    return token && raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function getSurveyToken() {
  const s = store()
  if (!s) return null
  // 예전 버전이 localStorage 에 남겨 둔 조사 세션은 이 창으로 한 번만 옮겨 온다
  if (!s.getItem(TOKEN)) {
    try {
      const old = localStorage.getItem(TOKEN)
      if (old) {
        s.setItem(TOKEN, old)
        const t = localStorage.getItem(TARGET)
        if (t) s.setItem(TARGET, t)
        localStorage.removeItem(TOKEN)
        localStorage.removeItem(TARGET)
      }
    } catch { /* noop */ }
  }
  return s.getItem(TOKEN)
}

export function endSurvey() {
  const s = store()
  if (!s) return
  s.removeItem(TOKEN)
  s.removeItem(TARGET)
}

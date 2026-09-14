// 담당자가 어르신 조사를 직접 입력할 때 쓰는 임시 세션
const TOKEN = 'surveyToken'
const TARGET = 'surveyTarget'

export function startSurvey({ token, elderly_id, display_name }) {
  localStorage.setItem(TOKEN, token)
  localStorage.setItem(TARGET, JSON.stringify({ elderly_id, display_name }))
}

export function getSurveyTarget() {
  try {
    const raw = localStorage.getItem(TARGET)
    return localStorage.getItem(TOKEN) && raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function getSurveyToken() {
  return localStorage.getItem(TOKEN)
}

export function endSurvey() {
  localStorage.removeItem(TOKEN)
  localStorage.removeItem(TARGET)
}

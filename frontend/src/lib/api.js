import axios from 'axios'
import { clearAuth, isCurrentToken, readAuth } from './session'
import { getSurveyToken } from './surveySession'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 15000,
})

// 요청마다 JWT 자동 첨부
// 담당자가 어르신 조사를 직접 입력하는 동안에는 설문 API(/surveys/*)에만 조사용 토큰을 사용
api.interceptors.request.use((config) => {
  const url = config.url || ''
  const surveyToken = getSurveyToken()
  const token = (surveyToken && (url.startsWith('/surveys') || url.startsWith('surveys'))) ? surveyToken : readAuth('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 401 시 로그인 페이지로
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      let role = null
      try { role = JSON.parse(readAuth('user') || 'null')?.role } catch { role = null }
      // 이 창이 쓰던 토큰이 만료된 경우에만 공용 저장소까지 비운다.
      // (다른 창이 새로 로그인했다면 그 창의 세션은 건드리지 않는다)
      const used = (err.config?.headers?.Authorization || '').replace('Bearer ', '')
      clearAuth({ everywhere: isCurrentToken(used) })
      window.location.href = role === 'staff' ? '/staff-login' : '/login'
    }
    return Promise.reject(err)
  }
)

export default api

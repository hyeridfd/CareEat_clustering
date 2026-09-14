import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 15000,
})

// 요청마다 JWT 자동 첨부
// 담당자가 어르신 조사를 직접 입력하는 동안에는 설문 API(/surveys/*)에만 조사용 토큰을 사용
api.interceptors.request.use((config) => {
  const url = config.url || ''
  const surveyToken = localStorage.getItem('surveyToken')
  const token = (surveyToken && (url.startsWith('/surveys') || url.startsWith('surveys'))) ? surveyToken : localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 401 시 로그인 페이지로
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      let role = null
      try { role = JSON.parse(localStorage.getItem('user') || 'null')?.role } catch { role = null }
      localStorage.clear()
      window.location.href = role === 'staff' ? '/staff-login' : '/login'
    }
    return Promise.reject(err)
  }
)

export default api

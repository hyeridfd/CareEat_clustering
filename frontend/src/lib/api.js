import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',
  timeout: 15000,
})

// 요청마다 JWT 자동 첨부
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
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

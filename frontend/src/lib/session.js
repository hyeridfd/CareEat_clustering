// 창(탭)마다 독립된 로그인 세션
//
// 예전에는 토큰을 localStorage 에만 두어서, 같은 브라우저에 Care-Eat 창을 두 개 띄우면
// 한쪽의 로그인·로그아웃·401 처리가 다른 쪽 토큰까지 건드려 계속 튕기는 문제가 있었다.
//   · 읽기: 이 창(sessionStorage) 먼저, 없으면 localStorage 에서 물려받는다
//   · 쓰기: 두 곳 모두 (새 창도 로그인 상태를 물려받도록)
//   · 정리: 이 창만 지울지, 두 곳 다 지울지 선택
const AUTH_KEYS = ['token', 'user', 'isAdmin']

export function readAuth(key) {
  try {
    let v = sessionStorage.getItem(key)
    if (v === null) {
      v = localStorage.getItem(key)
      if (v !== null) sessionStorage.setItem(key, v)   // 새 창이 물려받음
    }
    return v
  } catch {
    return null
  }
}

export function writeAuth(key, value) {
  try {
    sessionStorage.setItem(key, value)
    localStorage.setItem(key, value)
  } catch { /* 사생활 보호 모드 등 */ }
}

export function clearAuth({ everywhere = true } = {}) {
  try {
    AUTH_KEYS.forEach((k) => {
      sessionStorage.removeItem(k)
      if (everywhere) localStorage.removeItem(k)
    })
    sessionStorage.removeItem('surveyToken')
    sessionStorage.removeItem('surveyTarget')
    if (everywhere) {
      localStorage.removeItem('surveyToken')
      localStorage.removeItem('surveyTarget')
    }
  } catch { /* noop */ }
}

// 이 창이 쓰던 토큰이 아직 공용 저장소에 그대로면 '정말 만료된 것'으로 본다.
// 다른 창이 새로 로그인해 토큰이 바뀌었다면 공용 저장소는 건드리지 않는다.
export function isCurrentToken(token) {
  try {
    return !!token && localStorage.getItem('token') === token
  } catch {
    return false
  }
}

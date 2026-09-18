import { create } from 'zustand'
import { clearAuth, readAuth, writeAuth } from './session'

const useAuthStore = create((set) => ({
  token: readAuth('token') || null,
  user: JSON.parse(readAuth('user') || 'null'),
  isAdmin: readAuth('isAdmin') === 'true',

  setAuth: (token, user, isAdmin = false) => {
    writeAuth('token', token)
    writeAuth('user', JSON.stringify(user))
    writeAuth('isAdmin', String(isAdmin))
    set({ token, user, isAdmin })
  },

  logout: () => {
    clearAuth()
    set({ token: null, user: null, isAdmin: false })
  },
}))

export default useAuthStore

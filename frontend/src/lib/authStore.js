import { create } from 'zustand'

const useAuthStore = create((set) => ({
  token: localStorage.getItem('token') || null,
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  isAdmin: localStorage.getItem('isAdmin') === 'true',

  setAuth: (token, user, isAdmin = false) => {
    localStorage.setItem('token', token)
    localStorage.setItem('user', JSON.stringify(user))
    localStorage.setItem('isAdmin', isAdmin)
    set({ token, user, isAdmin })
  },

  logout: () => {
    localStorage.clear()
    set({ token: null, user: null, isAdmin: false })
  },
}))

export default useAuthStore

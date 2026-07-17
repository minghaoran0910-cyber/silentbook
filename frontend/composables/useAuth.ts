/**
 * Auth composable - shared login state across pages
 */
import { ref, readonly } from 'vue'

const token = ref<string | null>(null)
const user = ref<import('~/utils/api').UserInfo | null>(null)
let initialized = false

export function useAuth() {
  // Initialize from localStorage once (client-side only)
  if (!initialized && import.meta.client) {
    initialized = true
    const u = localStorage.getItem('user_info')
    if (localStorage.getItem('authenticated') === 'true') token.value = 'cookie'
    if (u) try { user.value = JSON.parse(u) } catch {}
  }

  function setAuth(t: string, u: import('~/utils/api').UserInfo) {
    token.value = t
    user.value = u
    if (import.meta.client) {
      localStorage.setItem('authenticated', 'true')
      localStorage.setItem('user_info', JSON.stringify(u))
    }
  }

  function clearAuth() {
    token.value = null
    user.value = null
    if (import.meta.client) {
      localStorage.removeItem('authenticated')
      localStorage.removeItem('user_info')
      fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => {})
    }
  }

  const isAuthenticated = () => !!token.value

  return {
    token: readonly(token),
    user: readonly(user),
    isAuthenticated,
    setAuth,
    clearAuth,
  }
}

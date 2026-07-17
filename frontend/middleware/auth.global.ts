/**
 * 全局路由守卫：未登录用户自动跳转 /auth
 * 白名单：/auth, /forgot-password
 */
export default defineNuxtRouteMiddleware((to) => {
  // 白名单页面不拦截
  const publicPaths = ['/auth', '/forgot-password']
  if (publicPaths.includes(to.path)) {
    return
  }

  // 服务端 SSR 不检查（没有 localStorage）
  if (import.meta.server) return

  if (localStorage.getItem('authenticated') !== 'true') {
    return navigateTo('/auth')
  }
})

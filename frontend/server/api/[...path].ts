// Catch-all API proxy: /api/* → backend service
// 去掉对外部 nginx 反向代理的依赖，docker compose up 即可开箱即用。
// 浏览器端所有 /api/* 请求由 Nuxt server 转发到后端，同源，无跨域问题。
import { proxyRequest } from 'h3'

export default defineEventHandler((event) => {
  const target = (process.env.NUXT_SSR_API_BASE || 'http://backend:8000').replace(/\/$/, '')
  // /api/auth/login → /auth/login（去掉 /api 前缀，与后端路由对齐）
  const backendPath = event.path.replace(/^\/api/, '') || '/'
  return proxyRequest(event, `${target}${backendPath}`)
})

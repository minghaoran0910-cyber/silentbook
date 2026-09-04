// Catch-all API proxy: /api/* → backend service
// 去掉对外部 nginx 反向代理的依赖，docker compose up 即可开箱即用。
// 浏览器端所有 /api/* 请求由 Nuxt server 转发到后端，同源，无跨域问题。
//
// 注意：不使用 h3 的 proxyRequest / setResponseHeader——它们在当前
// h3/Node 组合下会 500（headers.entries 缺失、响应上下文缺失）。
// 这里只用标准 fetch + 原生 Response 转发。

const HOP_REQ = new Set(['host', 'connection', 'content-length'])
const HOP_RES = new Set([
  'connection',
  'content-encoding',
  'transfer-encoding',
  'keep-alive',
  'upgrade',
  'trailer',
])

export default defineEventHandler(async (event) => {
  const target = (process.env.NUXT_SSR_API_BASE || 'http://backend:8000').replace(/\/$/, '')
  // /api/auth/login → /auth/login（去掉 /api 前缀，与后端路由对齐；query 保留）
  const backendPath = event.path.replace(/^\/api/, '') || '/'
  const url = `${target}${backendPath}`
  const method = (event.method || 'GET').toUpperCase()

  const headers: Record<string, string> = {}
  for (const [k, v] of Object.entries(event.node.req.headers || {})) {
    if (HOP_REQ.has(k.toLowerCase())) continue
    if (Array.isArray(v)) headers[k] = v.join(', ')
    else if (v !== undefined) headers[k] = String(v)
  }

  let body: Buffer | undefined
  if (method !== 'GET' && method !== 'HEAD') {
    try {
      const raw = await readRawBody(event, false)
      if (raw) body = Buffer.isBuffer(raw) ? raw : Buffer.from(raw as string)
    } catch {
      body = undefined
    }
    if (!body || body.length === 0) {
      // 兜底：直接读 Node 请求流
      try {
        const chunks: Buffer[] = []
        for await (const chunk of event.node.req) {
          chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk))
        }
        if (chunks.length > 0) body = Buffer.concat(chunks)
      } catch {
        // 保持 undefined
      }
    }
  }

  let upstream: Response
  try {
    upstream = await fetch(url, { method, headers, body })
  } catch {
    throw createError({ statusCode: 502, statusMessage: '后端服务不可用' })
  }

  const out = new Headers()
  upstream.headers.forEach((value, key) => {
    if (HOP_RES.has(key.toLowerCase())) return
    if (key.toLowerCase() === 'set-cookie') return // 下面单独处理多 Cookie
    out.append(key, value)
  })
  const getter = (
    upstream.headers as unknown as { getSetCookie?: () => string[] }
  ).getSetCookie
  if (typeof getter === 'function') {
    for (const c of getter.call(upstream.headers)) out.append('set-cookie', c)
  }

  const buf = await upstream.arrayBuffer()
  return new Response(buf, { status: upstream.status, headers: out })
})

export default defineNuxtConfig({
  devtools: { enabled: process.env.NODE_ENV === 'development' },
  
  runtimeConfig: {
    public: {
      // 浏览器端用 localhost，SSR 端用 Docker 内部网络
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api'
    }
  },

  css: ['~/assets/css/main.css'],

  app: {
    head: {
      title: 'SilentBook - 财务自由，不是终点',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=5, user-scalable=yes' },
        { name: 'description', content: '全自动无感记账 + AI Agent 协同分析' },
        { name: 'theme-color', content: '#b45309' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' },
        { name: 'mobile-web-app-capable', content: 'yes' }
      ],
      link: [
        { rel: 'manifest', href: '/manifest.json' },
        { rel: 'apple-touch-icon', href: '/icon-192.png' }
      ]
    }
  }
})

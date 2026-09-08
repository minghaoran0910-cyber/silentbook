export default defineNuxtConfig({
  devtools: { enabled: false },

  modules: ['@vite-pwa/nuxt', '@element-plus/nuxt', '@nuxt/ui'],

  pwa: {
    registerType: 'autoUpdate',
    manifest: false,
    workbox: {
      navigateFallback: '/',
      runtimeCaching: [
        {
          urlPattern: /^\/api\/.*/i,
          handler: 'NetworkFirst',
          options: {
            cacheName: 'silentbook-api',
            expiration: { maxEntries: 100, maxAgeSeconds: 300 },
            networkTimeoutSeconds: 8,
          },
        },
      ],
    },
  },
  
  runtimeConfig: {
    public: {
      // 浏览器端用 localhost，SSR 端用 Docker 内部网络
      apiBase: process.env.NUXT_PUBLIC_API_BASE || '/api'
    }
  },

  css: ['~/assets/css/main.css'],

  app: {
    pageTransition: { name: 'sb-page', mode: 'out-in' },
    layoutTransition: { name: 'sb-layout', mode: 'out-in' },
    head: {
      title: 'SilentBook - 财务自由，不是终点',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, maximum-scale=5, user-scalable=yes' },
        { name: 'description', content: '全自动无感记账 + AI Agent 协同分析' },
        { name: 'theme-color', content: '#f8fafc' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'default' },
        { name: 'mobile-web-app-capable', content: 'yes' }
      ],
      link: [
        { rel: 'manifest', href: '/manifest.json' },
        { rel: 'apple-touch-icon', href: '/apple-touch-icon.png' }
      ],
      script: [
        {
          // 首屏前定主题+品牌，防闪烁：已保存 > 跟随系统 > 默认（纸墨浅色）
          innerHTML: `(function(){try{var b=localStorage.getItem('sb-brand');if(b!=='ink'&&b!=='linear'&&b!=='cozy'){b='ink';}var t=localStorage.getItem('sb-theme');if(t!=='light'&&t!=='dark'){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}var h=document.documentElement;h.setAttribute('data-brand',b);h.setAttribute('data-theme',t);h.classList.toggle('dark',t==='dark');}catch(e){document.documentElement.setAttribute('data-brand','ink');document.documentElement.setAttribute('data-theme','light');}})();`,
        }
      ]
    }
  }
})

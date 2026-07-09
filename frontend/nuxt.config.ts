export default defineNuxtConfig({
  devtools: { enabled: true },
  
  runtimeConfig: {
    public: {
      apiBase: process.env.NUXT_PUBLIC_API_BASE || 'http://localhost:8000'
    }
  },

  css: ['~/assets/css/main.css'],

  app: {
    head: {
      title: 'SilentBook - 财务自由，不是终点',
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1' },
        { name: 'description', content: '全自动无感记账 + AI Agent 协同分析' }
      ]
    }
  }
})

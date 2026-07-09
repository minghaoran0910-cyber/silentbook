<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <h1>🔐 SilentBook</h1>
        <p>财务自由，不是终点，是每一步的选择</p>
      </div>

      <!-- Tab 切换 -->
      <div class="tab-switch">
        <button
          :class="{ active: mode === 'login' }"
          @click="switchMode('login')"
        >登录</button>
        <button
          :class="{ active: mode === 'register' }"
          @click="switchMode('register')"
        >注册</button>
      </div>

      <!-- 注册模式 -->
      <form v-if="mode === 'register'" @submit.prevent="handleRegister">
        <div class="form-group">
          <label>邮箱</label>
          <input
            v-model="regForm.email"
            type="email"
            placeholder="user@example.com"
          >
          <span class="field-hint">或填手机号，至少填一个</span>
        </div>
        <div class="form-group">
          <label>手机号</label>
          <input
            v-model="regForm.phone"
            type="tel"
            placeholder="13800138000"
          >
        </div>
        <div class="form-group">
          <label>昵称（可选）</label>
          <input
            v-model="regForm.nickname"
            type="text"
            placeholder="怎么称呼你"
            maxlength="50"
          >
        </div>
        <div class="form-group">
          <label>密码</label>
          <input
            v-model="regForm.password"
            type="password"
            required
            minlength="6"
            placeholder="至少6位"
          >
        </div>
        <div class="form-group">
          <label>确认密码</label>
          <input
            v-model="regForm.confirmPassword"
            type="password"
            required
            placeholder="再次输入"
          >
        </div>
        <button type="submit" class="btn-primary" :disabled="!canRegister">
          注册
        </button>
      </form>

      <!-- 登录模式 -->
      <form v-else @submit.prevent="handleLogin">
        <div class="form-group">
          <label>邮箱或手机号</label>
          <input
            v-model="loginForm.account"
            type="text"
            required
            placeholder="user@example.com / 13800138000"
          >
        </div>
        <div class="form-group">
          <label>密码</label>
          <input
            v-model="loginForm.password"
            type="password"
            required
            placeholder="输入密码"
          >
        </div>
        <button type="submit" class="btn-primary" :disabled="!canLogin">
          登录
        </button>
      </form>

      <div v-if="error" class="error-message">{{ error }}</div>
      <div v-if="success" class="success-message">{{ success }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const mode = ref('login')
const error = ref('')
const success = ref('')

const regForm = reactive({
  email: '',
  phone: '',
  nickname: '',
  password: '',
  confirmPassword: ''
})

const loginForm = reactive({
  account: '',
  password: ''
})

const canRegister = computed(() => {
  const hasContact = regForm.email || regForm.phone
  return hasContact && regForm.password.length >= 6 && regForm.password === regForm.confirmPassword
})

const canLogin = computed(() => {
  return loginForm.account && loginForm.password
})

const switchMode = (m) => {
  mode.value = m
  error.value = ''
  success.value = ''
}

const apiBase = () => {
  const config = useRuntimeConfig()
  return config.public?.apiBase || 'http://localhost:8000'
}

const handleRegister = async () => {
  error.value = ''
  success.value = ''

  if (regForm.password !== regForm.confirmPassword) {
    error.value = '两次密码不一致'
    return
  }

  try {
    const resp = await fetch(`${apiBase()}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: regForm.email || undefined,
        phone: regForm.phone || undefined,
        password: regForm.password,
        nickname: regForm.nickname || undefined
      })
    })

    const data = await resp.json()

    if (resp.ok) {
      localStorage.setItem('auth_token', data.access_token)
      localStorage.setItem('user_info', JSON.stringify(data.user))
      success.value = '注册成功！正在跳转...'
      setTimeout(() => router.push('/'), 800)
    } else {
      error.value = data.detail || '注册失败'
    }
  } catch (e) {
    error.value = '注册失败: ' + e.message
  }
}

const handleLogin = async () => {
  error.value = ''
  success.value = ''

  try {
    const resp = await fetch(`${apiBase()}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account: loginForm.account,
        password: loginForm.password
      })
    })

    const data = await resp.json()

    if (resp.ok && data.access_token) {
      localStorage.setItem('auth_token', data.access_token)
      localStorage.setItem('user_info', JSON.stringify(data.user))
      success.value = '登录成功！'
      setTimeout(() => router.push('/'), 500)
    } else {
      error.value = data.detail || '登录失败'
    }
  } catch (e) {
    error.value = '登录失败: ' + e.message
  }
}
</script>

<style scoped>
.auth-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary);
  padding: 2rem;
}

.auth-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 3rem;
  max-width: 420px;
  width: 100%;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
}

.auth-header {
  text-align: center;
  margin-bottom: 2rem;
}

.auth-header h1 {
  color: var(--accent);
  font-size: 2rem;
  margin-bottom: 0.5rem;
}

.auth-header p {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.tab-switch {
  display: flex;
  gap: 0;
  margin-bottom: 1.5rem;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid var(--border);
}

.tab-switch button {
  flex: 1;
  padding: 0.6rem;
  background: var(--bg-primary);
  border: none;
  color: var(--text-secondary);
  font-size: 0.95rem;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-switch button.active {
  background: var(--accent);
  color: white;
  font-weight: 600;
}

.form-group {
  margin-bottom: 1.2rem;
}

.form-group label {
  display: block;
  color: var(--text-secondary);
  margin-bottom: 0.4rem;
  font-size: 0.9rem;
}

.form-group input {
  width: 100%;
  padding: 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 1rem;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
}

.field-hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-tertiary, #888);
  margin-top: 0.25rem;
}

.btn-primary {
  width: 100%;
  padding: 0.75rem;
  background: var(--accent);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
  border: 1px solid var(--danger);
  border-radius: 8px;
  font-size: 0.9rem;
}

.success-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(34, 197, 94, 0.1);
  color: var(--success);
  border: 1px solid var(--success);
  border-radius: 8px;
  font-size: 0.9rem;
}
</style>

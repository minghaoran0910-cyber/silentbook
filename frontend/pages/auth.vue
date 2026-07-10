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
          type="button"
        >登录</button>
        <button
          :class="{ active: mode === 'register' }"
          @click="switchMode('register')"
          type="button"
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
            autocomplete="email"
            :disabled="loading"
          >
          <span class="field-hint">或填手机号，至少填一个</span>
        </div>
        <div class="form-group">
          <label>手机号</label>
          <input
            v-model="regForm.phone"
            type="tel"
            placeholder="13800138000"
            autocomplete="tel"
            :disabled="loading"
          >
        </div>
        <div class="form-group">
          <label>昵称（可选）</label>
          <input
            v-model="regForm.nickname"
            type="text"
            placeholder="怎么称呼你"
            maxlength="50"
            :disabled="loading"
          >
        </div>
        <div class="form-group">
          <label>密码</label>
          <div class="password-wrapper">
            <input
              v-model="regForm.password"
              :type="showRegPassword ? 'text' : 'password'"
              required
              minlength="6"
              placeholder="至少6位"
              autocomplete="new-password"
              :disabled="loading"
              @input="clearError"
            >
            <button
              type="button"
              class="toggle-pwd"
              @click="showRegPassword = !showRegPassword"
              tabindex="-1"
            >{{ showRegPassword ? '🙈' : '👁️' }}</button>
          </div>
          <span v-if="regForm.password && regForm.password.length < 6" class="field-hint field-warn">密码至少6位</span>
        </div>
        <div class="form-group">
          <label>确认密码</label>
          <div class="password-wrapper">
            <input
              v-model="regForm.confirmPassword"
              :type="showRegConfirm ? 'text' : 'password'"
              required
              placeholder="再次输入"
              autocomplete="new-password"
              :disabled="loading"
              @input="clearError"
            >
            <button
              type="button"
              class="toggle-pwd"
              @click="showRegConfirm = !showRegConfirm"
              tabindex="-1"
            >{{ showRegConfirm ? '🙈' : '👁️' }}</button>
          </div>
          <span v-if="regForm.confirmPassword && regForm.password !== regForm.confirmPassword" class="field-hint field-warn">两次密码不一致</span>
        </div>
        <button type="submit" class="btn-primary" :disabled="!canRegister || loading">
          <span v-if="loading" class="spinner" />
          {{ loading ? '注册中...' : '注册' }}
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
            autocomplete="username"
            :disabled="loading"
            @input="clearError"
          >
        </div>
        <div class="form-group">
          <label>密码</label>
          <div class="password-wrapper">
            <input
              v-model="loginForm.password"
              :type="showPassword ? 'text' : 'password'"
              required
              placeholder="输入密码"
              autocomplete="current-password"
              :disabled="loading"
              @input="clearError"
              @keydown.enter="handleLogin"
            >
            <button
              type="button"
              class="toggle-pwd"
              @click="showPassword = !showPassword"
              tabindex="-1"
            >{{ showPassword ? '🙈' : '👁️' }}</button>
          </div>
        </div>
        <button type="submit" class="btn-primary" :disabled="!canLogin || loading">
          <span v-if="loading" class="spinner" />
          {{ loading ? '登录中...' : '登录' }}
        </button>
        <div class="forgot-link">
          <button type="button" class="link-btn" @click="navigateTo('/forgot-password')" :disabled="loading">忘记密码?</button>
        </div>
      </form>

      <div v-if="error" class="error-message">
        <span>⚠️ {{ error }}</span>
      </div>
      <div v-if="success" class="success-message">{{ success }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'

definePageMeta({ layout: 'blank' })

const { isAuthenticated, setAuth } = useAuth()
const mode = ref<'login' | 'register'>('login')
const loading = ref(false)
const error = ref('')
const success = ref('')

// Password visibility toggles
const showPassword = ref(false)
const showRegPassword = ref(false)
const showRegConfirm = ref(false)

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
  const passwordsMatch = regForm.password === regForm.confirmPassword
  return hasContact && regForm.password.length >= 6 && passwordsMatch
})

const canLogin = computed(() => {
  return loginForm.account.length > 0 && loginForm.password.length > 0
})

const switchMode = (m: 'login' | 'register') => {
  mode.value = m
  error.value = ''
  success.value = ''
}

const clearError = () => {
  if (error.value) error.value = ''
}

const apiBase = () => {
  const config = useRuntimeConfig()
  return config.public?.apiBase || '/api'
}

const handleRegister = async () => {
  error.value = ''
  success.value = ''
  if (regForm.password !== regForm.confirmPassword) {
    error.value = '两次密码不一致'
    return
  }

  loading.value = true
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

    if (resp.ok && data.access_token) {
      setAuth(data.access_token, data.user)
      success.value = '注册成功！正在跳转...'
      setTimeout(() => navigateTo('/'), 800)
    } else {
      error.value = data.detail || '注册失败'
    }
  } catch (e: any) {
    error.value = '注册失败: ' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

const handleLogin = async () => {
  error.value = ''
  success.value = ''

  loading.value = true
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
      setAuth(data.access_token, data.user)
      success.value = '登录成功！'
      setTimeout(() => navigateTo('/'), 500)
    } else {
      error.value = data.detail || '登录失败'
    }
  } catch (e: any) {
    error.value = '登录失败: ' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

// Auto-redirect if already logged in with valid token
onMounted(async () => {
  if (isAuthenticated()) {
    // 验证 token 是否仍然有效
    try {
      const config = useRuntimeConfig()
      const apiBase = config.public?.apiBase || '/api'
      const resp = await fetch(`${apiBase}/auth/me`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('auth_token')}` }
      })
      if (resp.ok) {
        navigateTo('/')
      } else {
        // Token 无效，清除
        localStorage.removeItem('auth_token')
        localStorage.removeItem('user_info')
        document.cookie = 'auth_token=; path=/; max-age=0'
      }
    } catch {
      // 网络错误，不清除 token
    }
  }
})
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
  transition: border-color 0.2s, opacity 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
}

.form-group input:disabled {
  opacity: 0.6;
}

.field-hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-tertiary, #888);
  margin-top: 0.25rem;
}

.field-warn {
  color: #f59e0b;
}

.password-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.password-wrapper input {
  padding-right: 2.5rem;
}

.toggle-pwd {
  position: absolute;
  right: 0.5rem;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 0.25rem;
  opacity: 0.7;
  transition: opacity 0.2s;
}

.toggle-pwd:hover {
  opacity: 1;
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
  transition: background 0.2s, opacity 0.2s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.spinner {
  width: 1rem;
  height: 1rem;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: white;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.error-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger, #ef4444);
  border: 1px solid var(--danger, #ef4444);
  border-radius: 8px;
  font-size: 0.9rem;
}

.success-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(34, 197, 94, 0.1);
  color: var(--success, #22c55e);
  border: 1px solid var(--success, #22c55e);
  border-radius: 8px;
  font-size: 0.9rem;
}

@media (max-width: 480px) {
  .auth-card {
    padding: 2rem 1.5rem;
    border-radius: 12px;
  }

  .auth-header h1 {
    font-size: 1.6rem;
  }

  .form-group input {
    font-size: 0.95rem;
    padding: 0.65rem;
  }
}

.forgot-link {
  text-align: center;
  margin-top: 1rem;
}

.link-btn {
  background: none;
  border: none;
  color: var(--accent);
  font-size: 0.85rem;
  cursor: pointer;
  padding: 0.25rem;
}

.link-btn:hover {
  text-decoration: underline;
}
</style>

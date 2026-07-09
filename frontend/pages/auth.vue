<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <h1>🔐 SilentBook</h1>
        <p>财务自由，不是终点，是每一步的选择</p>
      </div>

      <div v-if="!authEnabled" class="setup-mode">
        <h2>首次设置</h2>
        <p>请设置访问密码</p>
        <form @submit.prevent="setupPassword">
          <div class="form-group">
            <label>密码</label>
            <input 
              v-model="password" 
              type="password" 
              required 
              minlength="4"
              placeholder="至少4位"
            >
          </div>
          <div class="form-group">
            <label>确认密码</label>
            <input 
              v-model="confirmPassword" 
              type="password" 
              required 
              placeholder="再次输入"
            >
          </div>
          <button type="submit" class="btn-primary" :disabled="!canSetup">
            设置密码
          </button>
        </form>
      </div>

      <div v-else class="login-mode">
        <h2>登录</h2>
        <form @submit.prevent="login">
          <div class="form-group">
            <label>密码</label>
            <input 
              v-model="password" 
              type="password" 
              required 
              placeholder="输入密码"
            >
          </div>
          <button type="submit" class="btn-primary" :disabled="!password">
            登录
          </button>
        </form>
      </div>

      <div v-if="error" class="error-message">{{ error }}</div>
      <div v-if="success" class="success-message">{{ success }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const password = ref('')
const confirmPassword = ref('')
const authEnabled = ref(false)
const error = ref('')
const success = ref('')

const canSetup = computed(() => {
  return password.value.length >= 4 && password.value === confirmPassword.value
})

const checkAuthStatus = async () => {
  try {
    const config = useRuntimeConfig()
    const apiBase = config.public?.apiBase || 'http://localhost:8000'
    const resp = await fetch(`${apiBase}/auth/status`)
    const data = await resp.json()
    authEnabled.value = data.auth_enabled
  } catch (e) {
    console.error('检查认证状态失败:', e)
  }
}

const setupPassword = async () => {
  error.value = ''
  success.value = ''
  
  if (password.value !== confirmPassword.value) {
    error.value = '两次密码不一致'
    return
  }
  
  try {
    const config = useRuntimeConfig()
    const apiBase = config.public?.apiBase || 'http://localhost:8000'
    const resp = await fetch(`${apiBase}/auth/setup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value })
    })
    
    if (resp.ok) {
      success.value = '密码设置成功！请登录'
      authEnabled.value = true
      password.value = ''
      confirmPassword.value = ''
    } else {
      error.value = '设置失败'
    }
  } catch (e) {
    error.value = '设置失败: ' + e.message
  }
}

const login = async () => {
  error.value = ''
  
  try {
    const config = useRuntimeConfig()
    const apiBase = config.public?.apiBase || 'http://localhost:8000'
    const resp = await fetch(`${apiBase}/auth/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: password.value })
    })
    
    const data = await resp.json()
    
    if (resp.ok && data.token) {
      localStorage.setItem('auth_token', data.token)
      success.value = '登录成功！'
      setTimeout(() => router.push('/'), 500)
    } else {
      error.value = '密码错误'
    }
  } catch (e) {
    error.value = '登录失败: ' + e.message
  }
}

onMounted(checkAuthStatus)
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
  max-width: 400px;
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

h2 {
  color: var(--text-primary);
  margin-bottom: 1rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  color: var(--text-secondary);
  margin-bottom: 0.5rem;
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

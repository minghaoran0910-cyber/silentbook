<template>
  <div class="auth-container">
    <div class="auth-card">
      <div class="auth-header">
        <h1>🔐 密码找回</h1>
        <p>输入注册邮箱或手机号，获取重置链接</p>
      </div>

      <!-- Step 1: 输入账号 -->
      <form v-if="step === 1" @submit.prevent="handleRequest">
        <div class="form-group">
          <label>邮箱或手机号</label>
          <input
            v-model="account"
            type="text"
            required
            placeholder="user@example.com / 13800138000"
            :disabled="loading"
          >
        </div>
        <button type="submit" class="btn-primary" :disabled="!account || loading">
          <span v-if="loading" class="spinner" />
          {{ loading ? '发送中...' : '发送重置链接' }}
        </button>
        <div class="back-link">
          <button type="button" class="link-btn" @click="navigateTo('/auth')">返回登录</button>
        </div>
      </form>

      <!-- Step 2: 设置新密码 -->
      <form v-else-if="step === 2" @submit.prevent="handleReset">
        <div class="form-group">
          <label>新密码</label>
          <div class="password-wrapper">
            <input
              v-model="newPassword"
              :type="showPwd ? 'text' : 'password'"
              required
              minlength="6"
              placeholder="至少6位"
              :disabled="loading"
            >
            <button type="button" class="toggle-pwd" @click="showPwd = !showPwd" tabindex="-1">
              {{ showPwd ? '🙈' : '👁️' }}
            </button>
          </div>
          <span v-if="newPassword && newPassword.length < 6" class="field-hint field-warn">密码至少6位</span>
        </div>
        <div class="form-group">
          <label>确认密码</label>
          <div class="password-wrapper">
            <input
              v-model="confirmPassword"
              :type="showConfirm ? 'text' : 'password'"
              required
              placeholder="再次输入"
              :disabled="loading"
            >
            <button type="button" class="toggle-pwd" @click="showConfirm = !showConfirm" tabindex="-1">
              {{ showConfirm ? '🙈' : '👁️' }}
            </button>
          </div>
          <span v-if="confirmPassword && newPassword !== confirmPassword" class="field-hint field-warn">两次密码不一致</span>
        </div>
        <button type="submit" class="btn-primary" :disabled="!canReset || loading">
          <span v-if="loading" class="spinner" />
          {{ loading ? '重置中...' : '重置密码' }}
        </button>
      </form>

      <!-- Step 3: 成功 -->
      <div v-else class="success-block">
        <div class="success-icon">✅</div>
        <p>密码重置成功！</p>
        <button class="btn-primary" @click="navigateTo('/auth')">前往登录</button>
      </div>

      <div v-if="error" class="error-message">
        <span>⚠️ {{ error }}</span>
      </div>
      <div v-if="info" class="info-message">{{ info }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

definePageMeta({ layout: 'blank' })

const account = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const resetToken = ref('')
const step = ref(1)
const loading = ref(false)
const error = ref('')
const info = ref('')
const showPwd = ref(false)
const showConfirm = ref(false)

const canReset = computed(() => {
  return newPassword.value.length >= 6 && newPassword.value === confirmPassword.value
})

const apiBase = () => {
  const config = useRuntimeConfig()
  return config.public?.apiBase || '/api'
}

const handleRequest = async () => {
  error.value = ''
  info.value = ''
  loading.value = true
  try {
    const resp = await fetch(`${apiBase()}/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account: account.value })
    })
    const data = await resp.json()
    if (!resp.ok) {
      error.value = data.detail || '请求失败'
      return
    }
    // 开发模式：返回了 reset_token
    if (data.reset_token) {
      resetToken.value = data.reset_token
      info.value = '重置令牌已生成（开发模式），请设置新密码'
      step.value = 2
    } else {
      info.value = data.message || '重置链接已发送'
      // 生产模式：等用户从邮件点击链接回来
      // 检查 URL 中是否已有 token（从邮件链接跳转）
    }
  } catch (e: any) {
    error.value = '请求失败: ' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

const handleReset = async () => {
  error.value = ''
  loading.value = true
  try {
    const resp = await fetch(`${apiBase()}/auth/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        token: resetToken.value,
        new_password: newPassword.value
      })
    })
    const data = await resp.json()
    if (!resp.ok) {
      error.value = data.detail || '重置失败'
      return
    }
    step.value = 3
  } catch (e: any) {
    error.value = '重置失败: ' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

// 检查 URL 参数中是否有 token（从邮件链接跳转）
onMounted(() => {
  if (import.meta.client) {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('token')
    if (token) {
      resetToken.value = token
      step.value = 2
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
  font-size: 1.6rem;
  margin-bottom: 0.5rem;
}

.auth-header p {
  color: var(--text-secondary);
  font-size: 0.9rem;
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
  transition: border-color 0.2s;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
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

.field-hint {
  display: block;
  font-size: 0.75rem;
  color: var(--text-tertiary, #888);
  margin-top: 0.25rem;
}

.field-warn {
  color: #f59e0b;
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

.info-message {
  margin-top: 1rem;
  padding: 0.75rem;
  background: rgba(59, 130, 246, 0.1);
  color: var(--accent, #3b82f6);
  border: 1px solid var(--accent, #3b82f6);
  border-radius: 8px;
  font-size: 0.9rem;
}

.success-block {
  text-align: center;
  padding: 1.5rem 0;
}

.success-icon {
  font-size: 3rem;
  margin-bottom: 1rem;
}

.back-link,
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

@media (max-width: 480px) {
  .auth-card {
    padding: 2rem 1.5rem;
  }
}
</style>

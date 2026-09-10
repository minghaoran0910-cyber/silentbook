<template>
  <div
    class="auth-page flex min-h-screen items-center justify-center px-4 py-8"
    :style="{ background: 'var(--bg-primary)' }"
  >
    <UCard
      class="sb-surface auth-enter w-full max-w-md"
      :ui="{ body: 'p-6 sm:p-10' }"
    >
      <div class="mb-6 text-center">
        <h1
          class="brand-title text-2xl font-semibold"
          :style="{ color: 'var(--accent)' }"
        >
          SilentBook
        </h1>
        <p class="mt-2 text-sm" :style="{ color: 'var(--text-secondary)' }">
          财务自由，不是终点，是每一步的选择
        </p>
      </div>

      <UTabs
        :model-value="mode"
        :items="tabItems"
        :content="false"
        class="mb-6 w-full"
        @update:model-value="(v) => switchMode(v as 'login' | 'register')"
      />

      <!-- 注册模式 -->
      <UForm
        v-if="mode === 'register'"
        :state="regForm"
        class="flex min-w-0 flex-col gap-4"
        @submit="handleRegister"
      >
        <UFormField label="邮箱" name="email" hint="或填手机号，至少填一个">
          <UInput
            v-model="regForm.email"
            type="email"
            placeholder="user@example.com"
            autocomplete="email"
            :disabled="loading"
            class="sb-focus w-full"
          />
        </UFormField>
        <UFormField label="手机号" name="phone">
          <UInput
            v-model="regForm.phone"
            type="tel"
            placeholder="13800138000"
            autocomplete="tel"
            :disabled="loading"
            class="sb-focus w-full"
          />
        </UFormField>
        <UFormField label="昵称（可选）" name="nickname">
          <UInput
            v-model="regForm.nickname"
            type="text"
            placeholder="怎么称呼你"
            maxlength="50"
            :disabled="loading"
            class="sb-focus w-full"
          />
        </UFormField>
        <UFormField
          label="密码"
          name="password"
          required
          :error="regForm.password && regForm.password.length < 6 ? '密码至少6位' : undefined"
        >
          <UInput
            v-model="regForm.password"
            :type="showRegPassword ? 'text' : 'password'"
            required
            minlength="6"
            placeholder="至少6位"
            autocomplete="new-password"
            :disabled="loading"
            class="sb-focus w-full"
            @input="clearError"
          >
            <template #trailing>
              <UButton
                variant="ghost"
                color="neutral"
                size="xs"
                square
                tabindex="-1"
                :aria-label="showRegPassword ? '隐藏密码' : '显示密码'"
                @click="showRegPassword = !showRegPassword"
              >
                <template #leading>
                  <AppIcon :icon="showRegPassword ? 'EyeSlash' : 'Eye'" :size="17" />
                </template>
              </UButton>
            </template>
          </UInput>
        </UFormField>
        <UFormField
          label="确认密码"
          name="confirmPassword"
          required
          :error="regForm.confirmPassword && regForm.password !== regForm.confirmPassword ? '两次密码不一致' : undefined"
        >
          <UInput
            v-model="regForm.confirmPassword"
            :type="showRegConfirm ? 'text' : 'password'"
            required
            placeholder="再次输入"
            autocomplete="new-password"
            :disabled="loading"
            class="sb-focus w-full"
            @input="clearError"
          >
            <template #trailing>
              <UButton
                variant="ghost"
                color="neutral"
                size="xs"
                square
                tabindex="-1"
                :aria-label="showRegConfirm ? '隐藏密码' : '显示密码'"
                @click="showRegConfirm = !showRegConfirm"
              >
                <template #leading>
                  <AppIcon :icon="showRegConfirm ? 'EyeSlash' : 'Eye'" :size="17" />
                </template>
              </UButton>
            </template>
          </UInput>
        </UFormField>
        <UButton
          type="submit"
          block
          :loading="loading"
          :disabled="!canRegister || loading"
          class="pressable sb-cta"
          :label="loading ? '注册中...' : '注册'"
        />
      </UForm>

      <!-- 登录模式 -->
      <UForm
        v-else
        :state="loginForm"
        class="flex min-w-0 flex-col gap-4"
        @submit="handleLogin"
      >
        <UFormField label="邮箱或手机号" name="account" required>
          <UInput
            v-model="loginForm.account"
            type="text"
            required
            placeholder="user@example.com / 13800138000"
            autocomplete="username"
            :disabled="loading"
            class="sb-focus w-full"
            @input="clearError"
          />
        </UFormField>
        <UFormField label="密码" name="password" required>
          <UInput
            v-model="loginForm.password"
            :type="showPassword ? 'text' : 'password'"
            required
            placeholder="输入密码"
            autocomplete="current-password"
            :disabled="loading"
            class="sb-focus w-full"
            @input="clearError"
          >
            <template #trailing>
              <UButton
                variant="ghost"
                color="neutral"
                size="xs"
                square
                tabindex="-1"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <template #leading>
                  <AppIcon :icon="showPassword ? 'EyeSlash' : 'Eye'" :size="17" />
                </template>
              </UButton>
            </template>
          </UInput>
        </UFormField>
        <UButton
          type="submit"
          block
          :loading="loading"
          :disabled="!canLogin || loading"
          class="pressable sb-cta"
          :label="loading ? '登录中...' : '登录'"
        />
        <div class="text-center">
          <UButton
            variant="link"
            :disabled="loading"
            label="忘记密码?"
            @click="navigateTo('/forgot-password')"
          />
        </div>
      </UForm>

      <UAlert
        v-if="error"
        class="alert-pop mt-4"
        color="error"
        variant="soft"
        :title="error"
      >
        <template #leading>
          <AppIcon icon="Warning" :size="15" />
        </template>
      </UAlert>
      <UAlert
        v-if="success"
        class="alert-pop mt-4"
        color="success"
        variant="soft"
        :title="success"
      />
    </UCard>
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

const tabItems = [
  { label: '登录', value: 'login' },
  { label: '注册', value: 'register' },
]

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
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: regForm.email || undefined,
        phone: regForm.phone || undefined,
        password: regForm.password,
        nickname: regForm.nickname || undefined
      })
    })

    const data = await resp.json()

    if (resp.ok && data.user) {
      setAuth('cookie', data.user)
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
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account: loginForm.account,
        password: loginForm.password
      })
    })

    const data = await resp.json()

    if (resp.ok && data.user) {
      setAuth('cookie', data.user)
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
        credentials: 'include'
      })
      if (resp.ok) {
        navigateTo('/')
      } else {
        // Token 无效，清除
        localStorage.removeItem('authenticated')
        localStorage.removeItem('user_info')
      }
    } catch {
      // 网络错误，不清除 token
    }
  }
})
</script>

<style scoped>
/* 品牌标题：ink 下为衬线体，其余品牌跟随正文字体 */
.brand-title {
  font-family: var(--font-brand-display);
  letter-spacing: 0.01em;
}

/* 卡片入场：250ms 上浮 8px（仅 transform/opacity） */
.auth-enter {
  animation: sb-auth-rise 250ms ease-out both;
}
@keyframes sb-auth-rise {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* 表单聚焦环：品牌 accent 描边，不引入新色 */
.sb-focus:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: var(--radius-sm);
}

/* 按钮按压缩放：160ms ease-out 到 .97；键盘聚焦激活时零动画 */
.pressable {
  transition: transform 160ms ease-out;
}
.pressable:active:where(:not(:focus-visible)) {
  transform: scale(0.97);
}

/* 错误/成功提示：从触发处展开感（顶部 origin，微缩放 + 位移） */
.alert-pop {
  transform-origin: top center;
  animation: sb-alert-pop 180ms ease-out both;
}
@keyframes sb-alert-pop {
  from {
    opacity: 0;
    transform: scaleY(0.96) translateY(-2px);
  }
  to {
    opacity: 1;
    transform: scaleY(1) translateY(0);
  }
}

@media (max-width: 480px) {
  .auth-page {
    padding-left: 1rem;
    padding-right: 1rem;
    align-items: flex-start;
    padding-top: 3rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .auth-enter,
  .alert-pop {
    animation: none;
  }
  .pressable {
    transition: none;
  }
  .pressable:active:where(:not(:focus-visible)) {
    transform: none;
  }
}
</style>

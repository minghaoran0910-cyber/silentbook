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
          class="brand-title text-xl font-semibold"
          :style="{ color: 'var(--accent)' }"
        >
          密码找回
        </h1>
        <p class="mt-2 text-sm" :style="{ color: 'var(--text-secondary)' }">
          输入注册邮箱或手机号，获取重置链接
        </p>
      </div>

      <!-- Step 1: 输入账号 -->
      <UForm
        v-if="step === 1"
        :state="requestState"
        class="flex min-w-0 flex-col gap-4"
        @submit="handleRequest"
      >
        <UFormField label="邮箱或手机号" name="account" required>
          <UInput
            v-model="account"
            type="text"
            required
            placeholder="user@example.com / 13800138000"
            :disabled="loading"
            class="sb-focus w-full"
          />
        </UFormField>
        <UButton
          type="submit"
          block
          :loading="loading"
          :disabled="!account || loading"
          class="pressable sb-cta"
          :label="loading ? '发送中...' : '发送重置链接'"
        />
        <div class="text-center">
          <UButton
            variant="link"
            label="返回登录"
            @click="navigateTo('/auth')"
          />
        </div>
      </UForm>

      <!-- Step 2: 设置新密码 -->
      <UForm
        v-else-if="step === 2"
        :state="resetState"
        class="flex min-w-0 flex-col gap-4"
        @submit="handleReset"
      >
        <UFormField
          label="新密码"
          name="newPassword"
          required
          :error="newPassword && newPassword.length < 6 ? '密码至少6位' : undefined"
        >
          <UInput
            v-model="newPassword"
            :type="showPwd ? 'text' : 'password'"
            required
            minlength="6"
            placeholder="至少6位"
            :disabled="loading"
            class="sb-focus w-full"
          >
            <template #trailing>
              <UButton
                variant="ghost"
                color="neutral"
                size="xs"
                square
                tabindex="-1"
                :aria-label="showPwd ? '隐藏密码' : '显示密码'"
                @click="showPwd = !showPwd"
              >
                <template #leading>
                  <AppIcon :icon="showPwd ? 'EyeSlash' : 'Eye'" :size="17" />
                </template>
              </UButton>
            </template>
          </UInput>
        </UFormField>
        <UFormField
          label="确认密码"
          name="confirmPassword"
          required
          :error="confirmPassword && newPassword !== confirmPassword ? '两次密码不一致' : undefined"
        >
          <UInput
            v-model="confirmPassword"
            :type="showConfirm ? 'text' : 'password'"
            required
            placeholder="再次输入"
            :disabled="loading"
            class="sb-focus w-full"
          >
            <template #trailing>
              <UButton
                variant="ghost"
                color="neutral"
                size="xs"
                square
                tabindex="-1"
                :aria-label="showConfirm ? '隐藏密码' : '显示密码'"
                @click="showConfirm = !showConfirm"
              >
                <template #leading>
                  <AppIcon :icon="showConfirm ? 'EyeSlash' : 'Eye'" :size="17" />
                </template>
              </UButton>
            </template>
          </UInput>
        </UFormField>
        <UButton
          type="submit"
          block
          :loading="loading"
          :disabled="!canReset || loading"
          class="pressable sb-cta"
          :label="loading ? '重置中...' : '重置密码'"
        />
      </UForm>

      <!-- Step 3: 成功 -->
      <div v-else class="py-6 text-center">
        <div
          class="mb-4 flex justify-center"
          :style="{ color: 'var(--accent)' }"
        >
          <AppIcon icon="Check" :size="34" />
        </div>
        <p
          class="mb-6 text-base font-medium"
          :style="{ color: 'var(--text-primary)' }"
        >
          密码重置成功！
        </p>
        <UButton
          block
          label="前往登录"
          class="pressable"
          @click="navigateTo('/auth')"
        />
      </div>

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
        v-if="info"
        class="alert-pop mt-4"
        color="info"
        variant="soft"
        :title="info"
      />
    </UCard>
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

// UForm 绑定的 state 对象（字段与原逻辑一一对应）
const requestState = computed(() => ({ account: account.value }))
const resetState = computed(() => ({
  newPassword: newPassword.value,
  confirmPassword: confirmPassword.value,
}))

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

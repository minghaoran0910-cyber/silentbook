<template>
  <div class="mx-auto w-full max-w-[600px] px-4 py-6">
    <div class="mb-4">
      <h1 class="sb-h text-2xl font-semibold" style="color: var(--text-primary)">手动记账</h1>
    </div>

    <!-- Tab 切换 -->
    <UTabs v-model="tab" :items="tabItems" :content="false" class="mb-6 w-full" />

    <!-- 粘贴通知解析 -->
    <UCard
      v-if="tab === 'paste'"
      class="sb-surface"
      :ui="{ body: 'p-4 sm:p-6 flex flex-col gap-4' }"
    >
      <UFormField label="粘贴通知文本" name="notification">
        <UTextarea
          id="add-notify"
          v-model="notificationText"
          :rows="6"
          placeholder="在此粘贴银行或支付平台的通知短信...&#10;例如：&#10;招商银行&#10;您尾号1234的储蓄卡于12月25日在星巴克消费人民币38.50元"
          class="w-full"
        />
      </UFormField>
      <UButton
        type="button"
        class="pressable"
        :loading="parsing"
        :disabled="parsing || !notificationText.trim()"
        @click="parseAndCreate"
      >
        <template v-if="!parsing" #leading>
          <AppIcon icon="MagnifyingGlass" :size="15" />
        </template>
        {{ parsing ? '解析中...' : '解析并创建' }}
      </UButton>
      <UAlert
        v-if="parseResult && parseResult.status === 'created'"
        class="alert-pop"
        color="success"
        variant="soft"
        title="解析成功！"
      >
        <template #leading>
          <span class="check-pop"><AppIcon icon="Check" :size="16" /></span>
        </template>
        <template #description>
          <span class="font-medium tabular-nums">{{ parseResult.category }} | ¥{{ parseResult.amount }} | {{ parseResult.type === 'income' ? '收入' : '支出' }}</span>
          <span v-if="parseResult.abnormal_alert?.triggered" class="mt-1 inline-flex items-center gap-1 text-xs">
            <AppIcon icon="Warning" :size="14" /> 异常消费已触发分析
          </span>
        </template>
      </UAlert>
      <UAlert
        v-else-if="parseResult"
        class="alert-pop"
        color="error"
        variant="soft"
        :title="parseResult.reason || parseResult.status"
      >
        <template #leading>
          <AppIcon icon="X" :size="16" />
        </template>
      </UAlert>
    </UCard>

    <!-- 手动输入表单 -->
    <UCard
      v-if="tab === 'manual'"
      class="sb-surface"
      :ui="{ body: 'p-4 sm:p-6' }"
    >
      <form class="flex flex-col gap-5" @submit.prevent="submitTransaction">
        <UFormField label="类型" name="transaction_type">
          <div class="grid grid-cols-2 gap-3" role="group" aria-label="记账类型">
            <UButton
              type="button"
              class="pressable"
              :color="form.transaction_type === 'expense' ? 'error' : 'neutral'"
              :variant="form.transaction_type === 'expense' ? 'solid' : 'outline'"
              @click="form.transaction_type = 'expense'"
            >
              支出
            </UButton>
            <UButton
              type="button"
              class="pressable"
              :color="form.transaction_type === 'income' ? 'success' : 'neutral'"
              :variant="form.transaction_type === 'income' ? 'solid' : 'outline'"
              @click="form.transaction_type = 'income'"
            >
              收入
            </UButton>
          </div>
        </UFormField>

        <UFormField label="金额" name="amount" :error="amountError || undefined" required>
          <UInput
            id="add-amount"
            v-model.number="form.amount"
            type="number"
            step="0.01"
            min="0"
            placeholder="0.00"
            required
            autofocus
            class="amount-field w-full"
            @update:model-value="amountError = ''"
          />
        </UFormField>

        <UFormField label="分类" name="category">
          <USelectMenu
            v-model="form.category"
            :items="categoryOptions"
            placeholder="选择或输入新分类"
            search-input
            create-item="always"
            class="w-full"
            @create="onCreateCategory"
            @update:model-value="onCategoryChange"
          >
            <template #item-leading="{ item }">
              <AppIcon :icon="categoryStyleOf(item).icon" :color="categoryStyleOf(item).color" :size="16" />
            </template>
          </USelectMenu>
          <div v-if="form.category && form.category.trim()" class="mt-2 flex items-center gap-2 text-sm" style="color: var(--text-secondary)">
            <AppIcon :icon="selectedStyle.icon" :color="selectedStyle.color" :size="18" />
            <span class="inline-block size-2.5 rounded-full" :style="{ background: selectedStyle.color }" aria-hidden="true" />
            <span>{{ form.category.trim() }}</span>
          </div>
        </UFormField>

        <UFormField label="账户" name="account" required>
          <USelect
            v-model="form.account"
            :items="accountOptions"
            placeholder="选择账户"
            required
            class="w-full"
          />
        </UFormField>

        <UFormField label="描述" name="description">
          <UInput
            v-model="form.description"
            type="text"
            placeholder="例如：星巴克咖啡"
            class="w-full"
          />
        </UFormField>

        <UButton type="submit" block class="pressable sb-cta" :loading="submitting" :disabled="submitting">
          {{ submitting ? '保存中...' : '保存' }}
        </UButton>

        <UAlert
          v-if="messageType === 'success' && message"
          class="alert-pop"
          color="success"
          variant="soft"
          :title="message"
        >
          <template #leading>
            <span class="check-pop"><AppIcon icon="Check" :size="16" /></span>
          </template>
        </UAlert>
        <UAlert
          v-if="messageType === 'error' && message"
          class="alert-pop"
          color="error"
          variant="soft"
          :title="message"
        />
      </form>
    </UCard>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { createTransaction, parseNotification } from '~/utils/api'
import { getAllKnownCategories, assignAutoStyle, getCategoryIcon } from '~/utils/icons'

const router = useRouter()

const tab = ref('manual')
const tabItems = [
  { label: '手动输入', value: 'manual' },
  { label: '粘贴通知', value: 'paste' }
]
const notificationText = ref('')
const parsing = ref(false)
const parseResult = ref(null)

const form = ref({
  amount: null,
  category: '',
  account: '',
  description: '',
  transaction_type: 'expense'
})

// 12 个固定账户：与原原生 select 的 option 顺序/文案一字不差
const accountOptions = [
  '招商银行', '工商银行', '建设银行', '农业银行', '中国银行', '交通银行',
  '浦发银行', '支付宝', '微信支付', '美团', '京东', '现金'
]

const submitting = ref(false)
const message = ref('')
const messageType = ref('success')
// 金额校验失败的 inline 错误（字段下方展示，原 message 文案不变）
const amountError = ref('')

// 已知全量分类：输入新词时自动配色并落盘（颜色稳定不跳变）
const customTick = ref(0)
const categoryOptions = computed(() => {
  void customTick.value
  return getAllKnownCategories()
})
const onCategoryChange = (val) => {
  const name = (val || '').trim()
  if (!name) return
  assignAutoStyle(name)
  customTick.value++
}
// USelectMenu 新建词入口：等价原可建项下拉行为，照旧调 assignAutoStyle 落盘
const onCreateCategory = (term) => {
  const name = (term || '').trim()
  if (!name) return
  form.value.category = name
  onCategoryChange(name)
}
// 只读预览：不落盘，落盘只走 onCategoryChange / onCreateCategory
const categoryStyleOf = (name) => getCategoryIcon((name || '').trim() || '其他')
const selectedStyle = computed(() => categoryStyleOf(form.value.category))

const submitTransaction = async () => {
  if (!form.value.amount || form.value.amount <= 0) {
    amountError.value = '请输入有效金额'
    message.value = ''
    return
  }

  submitting.value = true
  message.value = ''
  amountError.value = ''

  try {
    await createTransaction({
      amount: form.value.amount,
      category: form.value.category,
      account: form.value.account,
      description: form.value.description || undefined,
      transaction_type: form.value.transaction_type,
      confidence: 1.0
    })
    message.value = '记账成功！'
    messageType.value = 'success'
    // 重置表单
    form.value = {
      amount: null,
      category: '',
      account: '',
      description: '',
      transaction_type: 'expense'
    }
    // 2秒后跳转到交易列表
    setTimeout(() => {
      router.push('/transactions')
    }, 2000)
  } catch (error) {
    message.value = '保存失败，请重试'
    messageType.value = 'error'
  } finally {
    submitting.value = false
  }
}

const parseAndCreate = async () => {
  parsing.value = true
  parseResult.value = null
  try {
    const result = await parseNotification({
      title: '',
      body: notificationText.value,
      source: 'manual_paste'
    })
    parseResult.value = result
    if (result.status === 'created') {
      notificationText.value = ''
    }
  } catch (error) {
    parseResult.value = { status: 'error', reason: error.data?.detail || error.message }
  } finally {
    parsing.value = false
  }
}

// 动线：Cmd/Ctrl+K 聚焦首字段；切 Tab 后聚焦对应首字段；挂载 autofocus 由金额 UInput 承担
const focusField = (id) => {
  if (typeof document === 'undefined') return
  const el = document.getElementById(id)
  if (el) el.focus({ preventScroll: false })
}
const onGlobalKeydown = (e) => {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    focusField(tab.value === 'paste' ? 'add-notify' : 'add-amount')
  }
}
watch(tab, (v) => {
  nextTick(() => focusField(v === 'paste' ? 'add-notify' : 'add-amount'))
})
onMounted(() => {
  window.addEventListener('keydown', onGlobalKeydown)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<style scoped>
/* 金额大字等宽：inner input 经 :deep 定死，不受 U* 主题字号覆盖；ink 下衬线展示体 */
.amount-field :deep(input) {
  font-family: var(--font-brand-display);
  font-size: 1.75rem;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 成功确认感：alert 由触发处展开（180ms）；对勾 0.45s 缩放淡入，不许 confetti */
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
.check-pop {
  display: inline-flex;
  animation: sb-check-pop 450ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes sb-check-pop {
  from {
    opacity: 0;
    transform: scale(0.4);
  }
  60% {
    opacity: 1;
    transform: scale(1.15);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

/* 提交按钮按压缩放；键盘聚焦激活时零动画 */
.pressable {
  transition: transform 160ms ease-out;
}
.pressable:active:where(:not(:focus-visible)) {
  transform: scale(0.97);
}
a:focus-visible,
button:focus-visible {
  transition: none;
}

/* 480px 单列：收紧内边距，金额字号略降，类型双钮不断裂 */
@media (max-width: 480px) {
  .amount-field :deep(input) {
    font-size: 1.5rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .alert-pop,
  .check-pop {
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

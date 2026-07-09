<template>
  <div class="container">
    <div class="header">
      <h1>手动记账</h1>
    </div>

    <!-- Tab 切换 -->
    <div class="tab-bar">
      <button :class="{ active: tab === 'manual' }" @click="tab = 'manual'" class="tab-btn">手动输入</button>
      <button :class="{ active: tab === 'paste' }" @click="tab = 'paste'" class="tab-btn">粘贴通知</button>
    </div>

    <!-- 粘贴通知解析 -->
    <div v-if="tab === 'paste'" class="paste-section">
      <div class="form-group">
        <label>粘贴通知文本</label>
        <textarea
          v-model="notificationText"
          class="textarea"
          placeholder="在此粘贴银行或支付平台的通知短信...&#10;例如：&#10;招商银行&#10;您尾号1234的储蓄卡于12月25日在星巴克消费人民币38.50元"
          rows="6"
        ></textarea>
      </div>
      <button type="button" @click="parseAndCreate" class="btn-primary" :disabled="parsing || !notificationText.trim()">
        {{ parsing ? '解析中...' : '🔍 解析并创建' }}
      </button>
      <div v-if="parseResult" class="parse-result">
        <div v-if="parseResult.status === 'created'" class="parse-success">
          ✅ 解析成功！
          <span class="parse-detail">{{ parseResult.category }} | ¥{{ parseResult.amount }} | {{ parseResult.type === 'income' ? '收入' : '支出' }}</span>
          <span v-if="parseResult.abnormal_alert?.triggered" class="abnormal-badge">⚠️ 异常消费已触发分析</span>
        </div>
        <div v-else class="parse-fail">
          ❌ {{ parseResult.reason || parseResult.status }}
        </div>
      </div>
    </div>

    <!-- 手动输入表单 -->
    <form v-if="tab === 'manual'" @submit.prevent="submitTransaction" class="form">
      <div class="form-group">
        <label>类型</label>
        <div class="type-toggle">
          <button 
            type="button" 
            :class="{ active: form.transaction_type === 'expense' }"
            @click="form.transaction_type = 'expense'"
            class="toggle-btn expense"
          >
            支出
          </button>
          <button 
            type="button" 
            :class="{ active: form.transaction_type === 'income' }"
            @click="form.transaction_type = 'income'"
            class="toggle-btn income"
          >
            收入
          </button>
        </div>
      </div>

      <div class="form-group">
        <label>金额</label>
        <input 
          v-model.number="form.amount" 
          type="number" 
          step="0.01" 
          min="0"
          placeholder="0.00"
          required
        />
      </div>

      <div class="form-group">
        <label>分类</label>
        <select v-model="form.category" required>
          <option value="">选择分类</option>
          <option value="餐饮">餐饮</option>
          <option value="交通">交通</option>
          <option value="购物">购物</option>
          <option value="娱乐">娱乐</option>
          <option value="生活">生活</option>
          <option value="医疗">医疗</option>
          <option value="教育">教育</option>
          <option value="投资">投资</option>
          <option value="工资">工资</option>
          <option value="其他">其他</option>
        </select>
      </div>

      <div class="form-group">
        <label>账户</label>
        <select v-model="form.account" required>
          <option value="">选择账户</option>
          <option value="cmb">招商银行</option>
          <option value="icbc">工商银行</option>
          <option value="ccb">建设银行</option>
          <option value="alipay">支付宝</option>
          <option value="wechat_pay">微信支付</option>
          <option value="cash">现金</option>
        </select>
      </div>

      <div class="form-group">
        <label>描述</label>
        <input 
          v-model="form.description" 
          type="text" 
          placeholder="例如：星巴克咖啡"
        />
      </div>

      <button type="submit" class="btn btn-primary" :disabled="submitting">
        {{ submitting ? '保存中...' : '保存' }}
      </button>

      <div v-if="message" :class="['message', messageType]">
        {{ message }}
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { createTransaction } from '~/utils/api'

const router = useRouter()

const tab = ref('manual')
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

const submitting = ref(false)
const message = ref('')
const messageType = ref('success')

const submitTransaction = async () => {
  if (!form.value.amount || form.value.amount <= 0) {
    message.value = '请输入有效金额'
    messageType.value = 'error'
    return
  }

  submitting.value = true
  message.value = ''

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
    const config = useRuntimeConfig()
    const apiBase = config.public?.apiBase || 'http://localhost:8000'
    const result = await $fetch(`${apiBase}/webhook/notify`, {
      method: 'POST',
      body: {
        body: notificationText.value,
        source: 'manual_paste'
      }
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
</script>

<style scoped>
.container {
  max-width: 600px;
  margin: 0 auto;
}

.header {
  margin-bottom: 1rem;
}

.tab-bar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 2rem;
  border-bottom: 1px solid var(--border);
}

.tab-btn {
  padding: 0.6rem 1.2rem;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 0.95rem;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-btn.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.paste-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.textarea {
  width: 100%;
  padding: 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.9rem;
  resize: vertical;
  font-family: inherit;
}

.textarea:focus {
  outline: none;
  border-color: var(--accent);
}

.parse-result {
  padding: 1rem;
  border-radius: 8px;
}

.parse-success {
  color: var(--success);
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.parse-detail {
  color: var(--text-primary);
  font-weight: 500;
}

.abnormal-badge {
  color: var(--warning, #f59e0b);
  font-size: 0.85rem;
}

.parse-fail {
  color: var(--danger);
}

.header h1 {
  font-size: 1.8rem;
  color: var(--text-primary);
}

.form {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2rem;
}

.form-group {
  margin-bottom: 1.5rem;
}

.form-group label {
  display: block;
  color: var(--text-primary);
  font-weight: 500;
  margin-bottom: 0.5rem;
}

.form-group input,
.form-group select {
  width: 100%;
  padding: 0.75rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 1rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--accent);
}

.type-toggle {
  display: flex;
  gap: 1rem;
}

.toggle-btn {
  flex: 1;
  padding: 0.75rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.2s;
}

.toggle-btn.expense.active {
  background: var(--danger);
  border-color: var(--danger);
  color: white;
}

.toggle-btn.income.active {
  background: var(--success);
  border-color: var(--success);
  color: white;
}

.btn {
  width: 100%;
  padding: 0.75rem;
  border: none;
  border-radius: 8px;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.message {
  margin-top: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  text-align: center;
}

.message.success {
  background: rgba(34, 197, 94, 0.1);
  color: var(--success);
}

.message.error {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
}
</style>

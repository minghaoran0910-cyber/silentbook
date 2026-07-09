<template>
  <div class="container">
    <div class="header">
      <h1>手动记账</h1>
    </div>

    <form @submit.prevent="submitTransaction" class="form">
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

const router = useRouter()

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
    const response = await fetch('/api/transactions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...form.value,
        confidence: 1.0
      })
    })

    if (response.ok) {
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
    } else {
      throw new Error('保存失败')
    }
  } catch (error) {
    message.value = '保存失败，请重试'
    messageType.value = 'error'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.container {
  max-width: 600px;
  margin: 0 auto;
}

.header {
  margin-bottom: 2rem;
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

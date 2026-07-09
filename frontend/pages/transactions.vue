<template>
  <div class="container">
    <div class="page-header">
      <h1>交易记录</h1>
      <div class="header-actions">
        <button @click="showAddForm = !showAddForm" class="btn btn-primary">
          {{ showAddForm ? '取消' : '+ 手动记账' }}
        </button>
        <button @click="refresh" class="btn btn-secondary">刷新</button>
      </div>
    </div>

    <!-- 手动记账表单 -->
    <div v-if="showAddForm" class="add-form">
      <h3>新增交易</h3>
      <form @submit.prevent="submitTransaction">
        <div class="form-row">
          <div class="form-group">
            <label>类型</label>
            <select v-model="form.transaction_type" required>
              <option value="expense">支出</option>
              <option value="income">收入</option>
            </select>
          </div>
          <div class="form-group">
            <label>金额</label>
            <input type="number" v-model="form.amount" step="0.01" min="0.01" required placeholder="0.00">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>账户</label>
            <select v-model="form.account" required>
              <option value="cmb">招商银行</option>
              <option value="icbc">工商银行</option>
              <option value="ccb">建设银行</option>
              <option value="alipay">支付宝</option>
              <option value="wechat_pay">微信支付</option>
              <option value="cash">现金</option>
              <option value="other">其他</option>
            </select>
          </div>
          <div class="form-group">
            <label>分类</label>
            <select v-model="form.category" required>
              <option value="餐饮">餐饮</option>
              <option value="交通">交通</option>
              <option value="购物">购物</option>
              <option value="娱乐">娱乐</option>
              <option value="生活">生活</option>
              <option value="医疗">医疗</option>
              <option value="教育">教育</option>
              <option value="投资">投资</option>
              <option value="金融">金融</option>
              <option value="通讯">通讯</option>
              <option value="其他">其他</option>
            </select>
          </div>
        </div>

        <div class="form-group full-width">
          <label>描述</label>
          <input type="text" v-model="form.description" placeholder="备注（可选）">
        </div>

        <div class="form-actions">
          <button type="submit" class="btn btn-primary" :disabled="submitting">
            {{ submitting ? '保存中...' : '保存' }}
          </button>
        </div>
      </form>
    </div>

    <!-- 筛选 -->
    <div class="filters">
      <select v-model="filterAccount" @change="loadTransactions">
        <option value="">全部账户</option>
        <option value="cmb">招商银行</option>
        <option value="icbc">工商银行</option>
        <option value="ccb">建设银行</option>
        <option value="alipay">支付宝</option>
        <option value="wechat_pay">微信支付</option>
        <option value="cash">现金</option>
      </select>

      <select v-model="filterCategory" @change="loadTransactions">
        <option value="">全部分类</option>
        <option value="餐饮">餐饮</option>
        <option value="交通">交通</option>
        <option value="购物">购物</option>
        <option value="娱乐">娱乐</option>
        <option value="生活">生活</option>
        <option value="医疗">医疗</option>
        <option value="教育">教育</option>
        <option value="投资">投资</option>
        <option value="其他">其他</option>
      </select>

      <select v-model="filterType" @change="loadTransactions">
        <option value="">全部类型</option>
        <option value="expense">支出</option>
        <option value="income">收入</option>
      </select>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="transactions.length === 0" class="empty">
      暂无交易记录
    </div>

    <div v-else class="transaction-list">
      <div v-for="tx in transactions" :key="tx.id" class="transaction-item">
        <div class="tx-icon" :class="tx.transaction_type">
          {{ tx.transaction_type === 'income' ? '↓' : '↑' }}
        </div>
        <div class="tx-info">
          <div class="tx-description">{{ tx.description || tx.category }}</div>
          <div class="tx-meta">
            <span class="tx-account">{{ getAccountName(tx.account) }}</span>
            <span class="tx-category">{{ tx.category }}</span>
            <span class="tx-time">{{ formatTime(tx.parsed_at) }}</span>
          </div>
        </div>
        <div class="tx-amount" :class="tx.transaction_type">
          {{ tx.transaction_type === 'income' ? '+' : '-' }}¥{{ tx.amount.toFixed(2) }}
        </div>
        <button @click="handleDelete(tx.id)" class="tx-delete" title="删除">×</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchTransactions, createTransaction, deleteTransaction } from '~/utils/api'

const transactions = ref([])
const loading = ref(true)
const filterAccount = ref('')
const filterCategory = ref('')
const filterType = ref('')

// 手动记账
const showAddForm = ref(false)
const submitting = ref(false)
const form = ref({
  amount: null,
  category: '餐饮',
  account: 'wechat_pay',
  description: '',
  transaction_type: 'expense'
})

const loadTransactions = async () => {
  loading.value = true
  try {
    const params = {}
    if (filterAccount.value) params.account = filterAccount.value
    if (filterCategory.value) params.category = filterCategory.value
    if (filterType.value) params.transaction_type = filterType.value
    transactions.value = await fetchTransactions(params)
  } catch (error) {
    console.error('加载交易失败:', error)
  } finally {
    loading.value = false
  }
}

const refresh = () => {
  loadTransactions()
}

const submitTransaction = async () => {
  if (!form.value.amount || form.value.amount <= 0) return
  submitting.value = true
  try {
    await createTransaction({
      amount: form.value.amount,
      category: form.value.category,
      account: form.value.account,
      description: form.value.description || undefined,
      transaction_type: form.value.transaction_type,
      confidence: 1.0  // manual entry = full confidence
    })
    // reset form
    form.value.amount = null
    form.value.description = ''
    showAddForm.value = false
    await loadTransactions()
  } catch (error) {
    console.error('创建交易失败:', error)
    alert('保存失败，请重试')
  } finally {
    submitting.value = false
  }
}

const getAccountName = (account) => {
  const names = {
    cmb: '招商银行',
    icbc: '工商银行',
    ccb: '建设银行',
    alipay: '支付宝',
    wechat_pay: '微信支付',
    cash: '现金',
    other: '其他'
  }
  return names[account] || account
}

const formatTime = (time) => {
  const date = new Date(time)
  const now = new Date()
  const diff = now - date

  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`

  return date.toLocaleDateString('zh-CN')
}

const handleDelete = async (id) => {
  if (!confirm('确定要删除这条交易记录吗？')) return
  try {
    await deleteTransaction(id)
    await loadTransactions()
  } catch (error) {
    console.error('删除失败:', error)
  }
}

onMounted(() => {
  loadTransactions()
})
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.page-header h1 {
  color: var(--text-primary);
  font-size: 1.8rem;
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.btn {
  padding: 0.5rem 1.5rem;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
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

.btn-secondary {
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.btn-secondary:hover {
  border-color: var(--accent);
}

/* Form */
.add-form {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 2rem;
}

.add-form h3 {
  color: var(--text-primary);
  margin-bottom: 1rem;
}

.form-row {
  display: flex;
  gap: 1rem;
  margin-bottom: 1rem;
}

.form-group {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.form-group.full-width {
  margin-bottom: 1rem;
}

.form-group label {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.form-group input,
.form-group select {
  padding: 0.5rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 0.95rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--accent);
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}

/* Filters */
.filters {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
}

.filters select {
  padding: 0.5rem 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;
}

.loading, .empty {
  text-align: center;
  padding: 3rem;
  color: var(--text-secondary);
}

/* Transaction list */
.transaction-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.transaction-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-secondary);
  border-radius: 12px;
  transition: all 0.2s;
}

.transaction-item:hover {
  background: var(--bg-tertiary, rgba(255,255,255,0.03));
}

.tx-icon {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  font-weight: bold;
  flex-shrink: 0;
}

.tx-icon.income {
  background: rgba(34, 197, 94, 0.2);
  color: var(--success);
}

.tx-icon.expense {
  background: rgba(239, 68, 68, 0.2);
  color: var(--danger);
}

.tx-info {
  flex: 1;
  min-width: 0;
}

.tx-description {
  color: var(--text-primary);
  font-weight: 500;
  margin-bottom: 0.25rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tx-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.tx-amount {
  font-size: 1.2rem;
  font-weight: 600;
  flex-shrink: 0;
}

.tx-amount.income {
  color: var(--success);
}

.tx-amount.expense {
  color: var(--danger);
}

.tx-delete {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  opacity: 0;
  transition: all 0.2s;
}

.transaction-item:hover .tx-delete {
  opacity: 1;
}

.tx-delete:hover {
  color: var(--danger);
  background: rgba(239, 68, 68, 0.1);
}

@media (max-width: 768px) {
  .form-row {
    flex-direction: column;
  }
  .filters {
    flex-direction: column;
  }
  .tx-meta {
    flex-wrap: wrap;
    gap: 0.5rem;
  }
}
</style>

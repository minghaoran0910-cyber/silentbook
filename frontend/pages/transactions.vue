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

    <!-- 汇总统计 -->
    <div class="summary-bar" v-if="!loading && transactions.length > 0">
      <div class="summary-item">
        <span class="summary-label">共</span>
        <span class="summary-value">{{ transactions.length }} 笔</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">收入</span>
        <span class="summary-value income">+¥{{ summaryIncome.toFixed(2) }}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">支出</span>
        <span class="summary-value expense">-¥{{ summaryExpense.toFixed(2) }}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">净额</span>
        <span class="summary-value" :class="summaryIncome - summaryExpense >= 0 ? 'income' : 'expense'">
          ¥{{ (summaryIncome - summaryExpense).toFixed(2) }}
        </span>
      </div>
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

      <select v-model="filterDateRange" @change="loadTransactions">
        <option value="">全部时间</option>
        <option value="today">今天</option>
        <option value="week">最近7天</option>
        <option value="month">最近30天</option>
      </select>
    </div>

    <div v-if="loading" class="loading">加载中...</div>

    <div v-else-if="transactions.length === 0" class="empty">
      <div class="empty-icon">📭</div>
      <div class="empty-text">暂无交易记录</div>
      <button @click="showAddForm = true" class="btn btn-primary" style="margin-top: 1rem;">记一笔</button>
    </div>

    <div v-else class="transaction-list">
      <div v-for="tx in transactions" :key="tx.id" class="transaction-item" 
           :class="{ editing: editingId === tx.id }"
           @click="startEdit(tx)">
        <div class="tx-icon" :style="{ background: getCategoryIcon(tx.category).color + '20' }">
          <span class="icon-emoji">{{ getCategoryIcon(tx.category).icon }}</span>
        </div>
        <div class="tx-info">
          <div class="tx-description">{{ tx.description || tx.category }}</div>
          <div class="tx-meta">
            <span class="tx-account">{{ getAccountName(tx.account) }}</span>
            <span class="tx-category">{{ tx.category }}</span>
            <span class="tx-time">{{ formatTime(tx.parsed_at) }}</span>
            <span v-if="tx.confidence < 1" class="tx-confidence" :title="`置信度: ${(tx.confidence * 100).toFixed(0)}%`">
              {{ (tx.confidence * 100).toFixed(0) }}%
            </span>
          </div>
        </div>
        <div class="tx-amount" :class="tx.transaction_type">
          {{ tx.transaction_type === 'income' ? '+' : '-' }}¥{{ tx.amount.toFixed(2) }}
        </div>
        <button @click.stop="handleDelete(tx.id)" class="tx-delete" title="删除">×</button>
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <div v-if="editingId" class="edit-overlay" @click.self="cancelEdit">
      <div class="edit-modal">
        <h3>编辑交易</h3>
        <form @submit.prevent="submitEdit">
          <div class="form-row">
            <div class="form-group">
              <label>类型</label>
              <select v-model="editForm.transaction_type">
                <option value="expense">支出</option>
                <option value="income">收入</option>
              </select>
            </div>
            <div class="form-group">
              <label>金额</label>
              <input type="number" v-model="editForm.amount" step="0.01" min="0.01" required>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>账户</label>
              <select v-model="editForm.account">
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
              <select v-model="editForm.category">
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
            <input type="text" v-model="editForm.description" placeholder="备注">
          </div>
          <div class="edit-actions">
            <button type="button" @click="cancelEdit" class="btn btn-secondary">取消</button>
            <button type="submit" class="btn btn-primary" :disabled="submitting">
              {{ submitting ? '保存中...' : '保存修改' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated } from 'vue'
import { fetchTransactions, createTransaction, updateTransaction, deleteTransaction } from '~/utils/api'
import { getCategoryIcon } from '~/utils/icons'

const transactions = ref([])
const loading = ref(true)
const filterAccount = ref('')
const filterCategory = ref('')
const filterType = ref('')
const filterDateRange = ref('')

// 汇总
const summaryIncome = computed(() => 
  transactions.value.filter(t => t.transaction_type === 'income').reduce((s, t) => s + t.amount, 0)
)
const summaryExpense = computed(() => 
  transactions.value.filter(t => t.transaction_type === 'expense').reduce((s, t) => s + t.amount, 0)
)

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

// 编辑
const editingId = ref(null)
const clientReady = ref(false)
const editForm = ref({ amount: 0, category: '', account: '', description: '', transaction_type: 'expense' })

const loadTransactions = async () => {
  loading.value = true
  try {
    const params = {}
    if (filterAccount.value) params.account = filterAccount.value
    if (filterCategory.value) params.category = filterCategory.value
    if (filterType.value) params.transaction_type = filterType.value
    params.limit = 500
    const all = await fetchTransactions(params)
    
    // 前端日期过滤（后端暂不支持日期范围）
    if (filterDateRange.value) {
      const now = new Date()
      let cutoff
      if (filterDateRange.value === 'today') {
        cutoff = new Date(now.getFullYear(), now.getMonth(), now.getDate())
      } else if (filterDateRange.value === 'week') {
        cutoff = new Date(now.getTime() - 7 * 86400000)
      } else if (filterDateRange.value === 'month') {
        cutoff = new Date(now.getTime() - 30 * 86400000)
      }
      transactions.value = all.filter(t => new Date(t.parsed_at) >= cutoff)
    } else {
      transactions.value = all
    }
  } catch (error) {
    console.error('加载交易失败:', error)
  } finally {
    loading.value = false
  }
}

const refresh = () => { loadTransactions() }

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
      confidence: 1.0
    })
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

const startEdit = (tx) => {
  editingId.value = tx.id
  editForm.value = {
    amount: tx.amount,
    category: tx.category,
    account: tx.account,
    description: tx.description || '',
    transaction_type: tx.transaction_type
  }
}

const cancelEdit = () => { editingId.value = null }

const submitEdit = async () => {
  if (!editingId.value) return
  submitting.value = true
  try {
    await updateTransaction(editingId.value, {
      amount: editForm.value.amount,
      category: editForm.value.category,
      account: editForm.value.account,
      description: editForm.value.description || undefined,
      transaction_type: editForm.value.transaction_type
    })
    editingId.value = null
    await loadTransactions()
  } catch (error) {
    console.error('更新失败:', error)
    alert('更新失败，请重试')
  } finally {
    submitting.value = false
  }
}

const getAccountName = (account) => {
  const names = {
    cmb: '招商银行', icbc: '工商银行', ccb: '建设银行',
    alipay: '支付宝', wechat_pay: '微信支付', cash: '现金', other: '其他'
  }
  return names[account] || account
}

const formatTime = (time) => {
  const date = new Date(time)
  if (!clientReady.value) return date.toLocaleDateString('zh-CN')
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

const init = () => { setTimeout(() => { clientReady.value = true }, 0); loadTransactions() }
onMounted(init)
onActivated(init) // 客户端路由导航回来时也重新加载
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

/* Summary bar */
.summary-bar {
  display: flex;
  gap: 2rem;
  padding: 1rem 1.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 1.5rem;
}

.summary-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.summary-label {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.summary-value {
  color: var(--text-primary);
  font-weight: 600;
  font-size: 1rem;
}

.summary-value.income { color: var(--success); }
.summary-value.expense { color: var(--danger); }

/* Filters */
.filters {
  display: flex;
  gap: 1rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
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

.empty-icon { font-size: 3rem; margin-bottom: 0.5rem; }
.empty-text { font-size: 1.1rem; }

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
  cursor: pointer;
}

.transaction-item:hover {
  background: var(--bg-tertiary, rgba(255,255,255,0.03));
}

.transaction-item.editing {
  border: 1px solid var(--accent);
}

.tx-icon {
  width: 40px;
  height: 40px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.2rem;
  flex-shrink: 0;
}

.icon-emoji { font-size: 1.3rem; }

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
  gap: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
  align-items: center;
  flex-wrap: wrap;
}

.tx-confidence {
  background: rgba(245, 158, 11, 0.2);
  color: #F59E0B;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  font-size: 0.75rem;
}

.tx-amount {
  font-size: 1.2rem;
  font-weight: 600;
  flex-shrink: 0;
}

.tx-amount.income { color: var(--success); }
.tx-amount.expense { color: var(--danger); }

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

/* Edit modal */
.edit-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.edit-modal {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 2rem;
  width: 90%;
  max-width: 500px;
}

.edit-modal h3 {
  color: var(--text-primary);
  margin-bottom: 1.5rem;
}

.edit-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
}

@media (max-width: 768px) {
  .form-row { flex-direction: column; }
  .filters { flex-direction: column; }
  .summary-bar { flex-wrap: wrap; gap: 1rem; }
  .tx-meta { flex-wrap: wrap; gap: 0.5rem; }
}
</style>

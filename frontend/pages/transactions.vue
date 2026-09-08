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
            <el-select v-model="form.transaction_type" style="width: 100%">
              <el-option value="expense" label="支出" />
              <el-option value="income" label="收入" />
            </el-select>
          </div>
          <div class="form-group">
            <label>金额</label>
            <input type="number" v-model="form.amount" step="0.01" min="0.01" required placeholder="0.00">
          </div>
        </div>

        <div class="form-row">
          <div class="form-group">
            <label>账户</label>
            <el-select v-model="form.account" style="width: 100%">
              <el-option value="cmb" label="招商银行" />
              <el-option value="icbc" label="工商银行" />
              <el-option value="ccb" label="建设银行" />
              <el-option value="alipay" label="支付宝" />
              <el-option value="wechat_pay" label="微信支付" />
              <el-option value="cash" label="现金" />
              <el-option value="other" label="其他" />
            </el-select>
          </div>
          <div class="form-group">
            <label>分类</label>
            <el-select
              v-model="form.category"
              filterable
              allow-create
              default-first-option
              placeholder="选择或输入新分类"
              @change="onCategoryCreate"
            >
              <el-option v-for="c in allCategories" :key="c" :value="c" :label="c" />
            </el-select>
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
      <label class="noise-filter-toggle">
        <input type="checkbox" v-model="hideNoise" @change="loadTransactions">
        <span class="toggle-label">仅显示真实交易</span>
      </label>

      <el-select v-model="filterAccount" @change="loadTransactions" placeholder="全部账户" class="filter-el">
        <el-option value="" label="全部账户" />
        <el-option value="cmb" label="招商银行" />
        <el-option value="icbc" label="工商银行" />
        <el-option value="ccb" label="建设银行" />
        <el-option value="abc" label="农业银行" />
        <el-option value="boc" label="中国银行" />
        <el-option value="bocom" label="交通银行" />
        <el-option value="spdb" label="浦发银行" />
        <el-option value="alipay" label="支付宝" />
        <el-option value="wechat_pay" label="微信支付" />
        <el-option value="meituan" label="美团" />
        <el-option value="jd" label="京东" />
        <el-option value="cash" label="现金" />
      </el-select>

      <el-select v-model="filterCategory" @change="loadTransactions" placeholder="全部分类" class="filter-el" filterable clearable>
        <el-option value="" label="全部分类" />
        <el-option v-for="c in allCategories" :key="c" :value="c" :label="c" />
      </el-select>

      <el-select v-model="filterType" @change="loadTransactions" placeholder="全部类型" class="filter-el filter-el-sm">
        <el-option value="" label="全部类型" />
        <el-option value="expense" label="支出" />
        <el-option value="income" label="收入" />
      </el-select>

      <el-select v-model="filterDateRange" @change="loadTransactions" placeholder="全部时间" class="filter-el">
        <el-option value="" label="全部时间" />
        <el-option value="today" label="今天" />
        <el-option value="week" label="最近7天" />
        <el-option value="month" label="最近30天" />
      </el-select>
    </div>

    <!-- Loading：el-skeleton，布局按现有 skeleton-list 对齐 -->
    <div v-if="loading" class="skeleton-list">
      <el-skeleton v-for="i in 6" :key="i" animated class="skeleton-item">
        <template #template>
          <el-skeleton-item variant="image" class="skeleton-icon" />
          <div class="skeleton-info">
            <el-skeleton-item variant="text" style="width: 60%" />
            <el-skeleton-item variant="text" style="width: 40%" />
          </div>
          <el-skeleton-item variant="text" class="skeleton-amount" />
        </template>
      </el-skeleton>
    </div>

    <!-- 空态：el-empty，保留文案与插画位 -->
    <el-empty v-else-if="transactions.length === 0" description="暂无交易记录" class="tx-empty">
      <template #image>
        <div class="empty-icon"><AppIcon icon="Package" :size="36" /></div>
      </template>
      <el-button type="primary" @click="showAddForm = true">记一笔</el-button>
    </el-empty>

    <TransitionGroup v-else name="tx-list" tag="div" class="transaction-list">
      <div v-for="tx in transactions" :key="tx.id" class="transaction-item"
           :class="{ editing: editingId === tx.id }"
           @click="startEdit(tx)">
        <div class="tx-icon" :style="{ background: getCategoryIcon(tx.category).color + '20' }">
          <AppIcon :icon="getCategoryIcon(tx.category).icon" :color="getCategoryIcon(tx.category).color" :size="20" />
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
        <button @click.stop="handleDelete(tx.id)" class="tx-delete" title="删除">×</button>
      </div>
    </TransitionGroup>

    <!-- 删除确认：el-dialog，颜色经 --el-* 桥接自动跟主题 -->
    <el-dialog v-model="deleteDialogVisible" title="删除交易" width="400" align-center>
      <span>确定要删除这条交易记录吗？此操作不可撤销。</span>
      <template #footer>
        <el-button @click="deleteDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="deleting" @click="confirmDelete">删除</el-button>
      </template>
    </el-dialog>

    <!-- 编辑弹窗 -->
    <div v-if="editingId" class="edit-overlay" @click.self="cancelEdit">
      <div class="edit-modal">
        <h3>编辑交易</h3>
        <form @submit.prevent="submitEdit">
          <div class="form-row">
            <div class="form-group">
              <label>类型</label>
              <el-select v-model="editForm.transaction_type" style="width: 100%">
                <el-option value="expense" label="支出" />
                <el-option value="income" label="收入" />
              </el-select>
            </div>
            <div class="form-group">
              <label>金额</label>
              <input type="number" v-model="editForm.amount" step="0.01" min="0.01" required>
            </div>
          </div>
          <div class="form-row">
            <div class="form-group">
              <label>账户</label>
              <el-select v-model="editForm.account" style="width: 100%">
                <el-option value="cmb" label="招商银行" />
                <el-option value="icbc" label="工商银行" />
                <el-option value="ccb" label="建设银行" />
                <el-option value="alipay" label="支付宝" />
                <el-option value="wechat_pay" label="微信支付" />
                <el-option value="cash" label="现金" />
                <el-option value="other" label="其他" />
              </el-select>
            </div>
            <div class="form-group">
              <label>分类</label>
              <el-select
                v-model="editForm.category"
                filterable
                allow-create
                default-first-option
                placeholder="选择或输入新分类"
                @change="onCategoryCreate"
              >
                <el-option v-for="c in allCategories" :key="c" :value="c" :label="c" />
              </el-select>
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
import { getCategoryIcon, getAllKnownCategories, assignAutoStyle } from '~/utils/icons'

const transactions = ref([])
const loading = ref(true)
const filterAccount = ref('')
const filterCategory = ref('')
const filterType = ref('')
const filterDateRange = ref('')
const hideNoise = ref(true)  // 默认隐藏0元垃圾通知

// 汇总
const summaryIncome = computed(() => 
  transactions.value.filter(t => t.transaction_type === 'income').reduce((s, t) => s + t.amount, 0)
)
const summaryExpense = computed(() => 
  transactions.value.filter(t => t.transaction_type === 'expense').reduce((s, t) => s + t.amount, 0)
)

// 已知全量分类（内置 + 生产种子 + 用户自定义，去重排序）；新建词自动配色落盘
const customTick = ref(0)
const allCategories = computed(() => {
  void customTick.value
  return getAllKnownCategories()
})
const onCategoryCreate = (val) => {
  const name = (val || '').trim()
  if (!name) return
  assignAutoStyle(name)
  customTick.value++
}

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
    if (hideNoise.value) params.hide_noise = true
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
    abc: '农业银行', boc: '中国银行', bocom: '交通银行', spdb: '浦发银行',
    ceb: '光大银行', citic: '中信银行', unionpay: '云闪付',
    alipay: '支付宝', wechat_pay: '微信支付',
    meituan: '美团', jd: '京东', taobao: '淘宝',
    cash: '现金', other: '其他'
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

// 删除确认（el-dialog）
const deleteDialogVisible = ref(false)
const pendingDeleteId = ref(null)
const deleting = ref(false)

const handleDelete = (id) => {
  pendingDeleteId.value = id
  deleteDialogVisible.value = true
}

const confirmDelete = async () => {
  if (!pendingDeleteId.value) return
  deleting.value = true
  try {
    await deleteTransaction(pendingDeleteId.value)
    deleteDialogVisible.value = false
    pendingDeleteId.value = null
    await loadTransactions()
  } catch (error) {
    console.error('删除失败:', error)
  } finally {
    deleting.value = false
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
  border-radius: var(--radius-md);
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: var(--accent);
  color: var(--accent-ink);
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
  border-radius: var(--radius-lg);
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

.form-group input {
  padding: 0.5rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-size: 0.95rem;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
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
  border-radius: var(--radius-md);
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
  gap: 0.75rem;
  margin-bottom: 2rem;
  flex-wrap: wrap;
  align-items: center;
}

.filter-el {
  width: 132px;
}

.filter-el-sm {
  width: 112px;
}

/* Noise filter toggle */
.noise-filter-toggle {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  padding: 0.5rem 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  user-select: none;
}

.noise-filter-toggle input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
  cursor: pointer;
}

.toggle-label {
  color: var(--text-primary);
  font-size: 0.9rem;
  white-space: nowrap;
}

.noise-filter-toggle:has(input:checked) {
  border-color: var(--accent);
  background: var(--accent-soft);
}

/* Skeleton：el-skeleton，布局按原 skeleton-list 对齐 */
.skeleton-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.skeleton-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
}

.skeleton-item .el-skeleton__image.skeleton-icon {
  width: 40px;
  height: 40px;
  border-radius: var(--radius-lg);
  flex-shrink: 0;
}

.skeleton-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.skeleton-item .el-skeleton__text.skeleton-amount {
  width: 80px;
  height: 20px;
  flex-shrink: 0;
}

.tx-empty {
  padding: 3rem 1rem;
}

.empty-icon { display: flex; justify-content: center; margin-bottom: 0.5rem; color: var(--text-tertiary); }

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
  border: 1px solid transparent;
  border-radius: var(--radius-lg);
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
  border-radius: var(--radius-lg);
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
  border-radius: var(--radius-sm);
  opacity: 0;
  transition: all 0.2s;
}

.transaction-item:hover .tx-delete {
  opacity: 1;
}

.tx-delete:hover {
  color: var(--danger);
  background: var(--danger-soft);
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
  border-radius: var(--radius-lg);
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
  .filters { flex-direction: column; align-items: stretch; }
  .summary-bar { flex-wrap: wrap; gap: 1rem; }
  .tx-meta { flex-wrap: wrap; gap: 0.5rem; }
}

@media (max-width: 480px) {
  .filter-el,
  .filter-el-sm { width: 100%; }
  .edit-modal { width: calc(100vw - 2rem); padding: 1.25rem; }
}

/* 触屏无 hover：删除按钮常显 */
@media (hover: none) {
  .transaction-item .tx-delete { opacity: 1; }
}
</style>

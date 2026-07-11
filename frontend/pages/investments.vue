<template>
  <div class="container">
    <div class="header">
      <h1>📈 投资持仓</h1>
      <div class="header-actions">
        <button @click="syncPositions" class="btn btn-sync" :disabled="syncing">
          {{ syncing ? '同步中...' : '🔄 同步持仓' }}
        </button>
        <button @click="toggleAddForm" class="btn btn-primary">
          {{ showAddForm ? '取消' : '+ 添加持仓' }}
        </button>
      </div>
    </div>

    <!-- 同步状态 -->
    <div v-if="syncResult" class="sync-result" :class="syncResult.error ? 'error' : 'success'">
      <span>{{ syncResult.message }}</span>
      <span v-if="syncResult.updated">更新 {{ syncResult.updated }} 个</span>
      <span v-if="syncResult.failed">失败 {{ syncResult.failed }} 个</span>
      <button @click="syncResult = null" class="close-btn">×</button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-state">
      <div class="spinner"></div>
      <p>加载投资数据...</p>
    </div>

    <div v-else-if="loadError" class="error-state">
      <p>⚠️ {{ loadError }}</p>
      <button @click="loadData" class="btn btn-primary">重试</button>
    </div>

    <!-- 总览卡片 -->
    <div class="overview" v-if="!loading && !loadError">
      <div class="overview-card">
        <div class="label">总市值</div>
        <div class="value">¥{{ formatNum(summary.total_value) }}</div>
      </div>
      <div class="overview-card">
        <div class="label">总成本</div>
        <div class="value">¥{{ formatNum(summary.total_cost) }}</div>
      </div>
      <div class="overview-card" :class="summary.total_profit >= 0 ? 'profit' : 'loss'">
        <div class="label">总收益</div>
        <div class="value">{{ summary.total_profit >= 0 ? '+' : '' }}¥{{ formatNum(summary.total_profit) }}</div>
      </div>
      <div class="overview-card" :class="summary.total_profit_pct >= 0 ? 'profit' : 'loss'">
        <div class="label">收益率</div>
        <div class="value">{{ summary.total_profit_pct >= 0 ? '+' : '' }}{{ summary.total_profit_pct.toFixed(2) }}%</div>
      </div>
    </div>

    <!-- 添加/编辑持仓表单 -->
    <div v-if="showAddForm && !loading" class="form-card">
      <h3>{{ editingId ? '编辑持仓' : '添加持仓' }}</h3>
      <form @submit.prevent="handleSubmit">
        <div class="form-grid">
          <div class="form-group">
            <label>名称</label>
            <input v-model="form.name" type="text" required placeholder="如：沪深300ETF" />
          </div>
          <div class="form-group">
            <label>代码</label>
            <input v-model="form.symbol" type="text" placeholder="如：510300" />
          </div>
          <div class="form-group">
            <label>类型</label>
            <select v-model="form.position_type" required>
              <option value="stock">股票</option>
              <option value="fund">基金</option>
              <option value="bond">债券</option>
              <option value="wealth_mgmt">银行理财</option>
              <option value="other">其他</option>
            </select>
          </div>
          <div class="form-group">
            <label>持有数量</label>
            <input v-model.number="form.quantity" type="number" step="0.01" required placeholder="股/份" />
          </div>
          <div class="form-group">
            <label>买入均价</label>
            <input v-model.number="form.avg_cost" type="number" step="0.0001" required placeholder="成本价" />
          </div>
          <div class="form-group">
            <label>当前价格</label>
            <input v-model.number="form.current_price" type="number" step="0.0001" placeholder="留空同步后自动更新" />
          </div>
          <div class="form-group">
            <label>所属账户</label>
            <input v-model="form.account" type="text" placeholder="如：东方财富证券" />
          </div>
          <div class="form-group">
            <label>备注</label>
            <input v-model="form.notes" type="text" placeholder="可选" />
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary" :disabled="submitting">
            {{ submitting ? '提交中...' : (editingId ? '保存' : '添加') }}
          </button>
          <button type="button" @click="resetForm" class="btn btn-secondary">重置</button>
        </div>
      </form>
    </div>

    <!-- 持仓列表 -->
    <div v-if="!loading && !loadError" class="section">
      <h2>持仓明细 ({{ positions.length }})</h2>
      <div v-if="positions.length === 0" class="empty-state">
        <p>暂无投资持仓</p>
        <p class="hint">点击"添加持仓"开始记录你的投资</p>
      </div>
      <div v-else class="position-list">
        <div v-for="pos in positions" :key="pos.id" class="position-card" :class="{ closed: pos.status === 'closed' }">
          <div class="position-header">
            <div class="position-name">
              <span class="type-badge" :class="pos.position_type">{{ typeLabel(pos.position_type) }}</span>
              <span class="name">{{ pos.name }}</span>
              <span v-if="pos.symbol" class="symbol">{{ pos.symbol }}</span>
            </div>
            <div class="position-actions">
              <button @click="editPosition(pos)" class="btn-icon" title="编辑">✏️</button>
              <button @click="deletePosition(pos.id)" class="btn-icon danger" title="关闭">🗑️</button>
            </div>
          </div>
          <div class="position-body">
            <div class="metric">
              <span class="metric-label">持有数量</span>
              <span class="metric-value">{{ pos.quantity }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">买入均价</span>
              <span class="metric-value">¥{{ formatNum(pos.avg_cost) }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">当前价格</span>
              <span class="metric-value">¥{{ formatNum(pos.current_price) }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">市值</span>
              <span class="metric-value">¥{{ formatNum(pos.market_value) }}</span>
            </div>
            <div class="metric">
              <span class="metric-label">收益</span>
              <span class="metric-value" :class="pos.profit >= 0 ? 'text-profit' : 'text-loss'">
                {{ pos.profit >= 0 ? '+' : '' }}¥{{ formatNum(pos.profit) }}
              </span>
            </div>
            <div class="metric">
              <span class="metric-label">收益率</span>
              <span class="metric-value" :class="pos.profit_pct >= 0 ? 'text-profit' : 'text-loss'">
                {{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(2) }}%
              </span>
            </div>
          </div>
          <div class="position-footer" v-if="pos.account || pos.updated_at">
            <span v-if="pos.account">📍 {{ pos.account }}</span>
            <span v-if="pos.updated_at">更新于 {{ formatTime(pos.updated_at) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

const { token } = useAuth()
const config = useRuntimeConfig()
const apiBase = config.public.apiBase

interface Position {
  id: number
  name: string
  symbol: string | null
  position_type: string
  quantity: number
  avg_cost: number
  current_price: number
  market_value: number
  cost_value: number
  profit: number
  profit_pct: number
  account: string | null
  status: string
  updated_at: string | null
}

const loading = ref(true)
const loadError = ref('')
const positions = ref<Position[]>([])
const summary = ref({ count: 0, total_value: 0, total_cost: 0, total_profit: 0, total_profit_pct: 0 })

const syncing = ref(false)
const syncResult = ref<any>(null)

const showAddForm = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)

const form = ref({
  name: '',
  symbol: '',
  position_type: 'fund',
  quantity: 0,
  avg_cost: 0,
  current_price: 0,
  account: '',
  notes: '',
})

function formatNum(n: number) {
  return Math.abs(n) >= 10000 ? (n / 10000).toFixed(2) + '万' : n.toFixed(2)
}

function formatTime(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

function typeLabel(t: string) {
  const map: Record<string, string> = { stock: '股票', fund: '基金', bond: '债券', wealth_mgmt: '理财', other: '其他' }
  return map[t] || t
}

async function apiFetch(path: string, options: RequestInit = {}) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token.value) headers['Authorization'] = `Bearer ${token.value}`
  const res = await fetch(`${apiBase}${path}`, { ...options, headers })
  if (res.status === 401) {
    const { clearAuth } = useAuth()
    clearAuth()
    navigateTo('/auth')
    throw new Error('未授权')
  }
  return res
}

async function loadData() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await apiFetch('/positions')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    positions.value = data.positions || []
    summary.value = data.summary || { count: 0, total_value: 0, total_cost: 0, total_profit: 0, total_profit_pct: 0 }
  } catch (e: any) {
    loadError.value = e.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function syncPositions() {
  syncing.value = true
  syncResult.value = null
  try {
    const res = await apiFetch('/sync/assets', { method: 'POST' })
    const data = await res.json()
    syncResult.value = {
      message: data.error ? `同步失败: ${data.message}` : '同步完成',
      updated: data.updated || 0,
      failed: data.failed || 0,
      error: !!data.error,
    }
    // Reload positions to get updated prices
    await loadData()
  } catch (e: any) {
    syncResult.value = { message: `同步请求失败: ${e.message}`, error: true }
  } finally {
    syncing.value = false
  }
}

function toggleAddForm() {
  showAddForm.value = !showAddForm.value
  if (!showAddForm.value) resetForm()
}

function resetForm() {
  editingId.value = null
  form.value = { name: '', symbol: '', position_type: 'fund', quantity: 0, avg_cost: 0, current_price: 0, account: '', notes: '' }
}

function editPosition(pos: Position) {
  editingId.value = pos.id
  form.value = {
    name: pos.name,
    symbol: pos.symbol || '',
    position_type: pos.position_type,
    quantity: pos.quantity,
    avg_cost: pos.avg_cost,
    current_price: pos.current_price,
    account: pos.account || '',
    notes: '',
  }
  showAddForm.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function handleSubmit() {
  submitting.value = true
  try {
    const body = { ...form.value }
    let res: Response
    if (editingId.value) {
      res = await apiFetch(`/positions/${editingId.value}`, { method: 'PUT', body: JSON.stringify(body) })
    } else {
      res = await apiFetch('/positions', { method: 'POST', body: JSON.stringify(body) })
    }
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail || '操作失败')
    }
    showAddForm.value = false
    resetForm()
    await loadData()
  } catch (e: any) {
    alert(e.message || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function deletePosition(id: number) {
  if (!confirm('确认关闭此持仓？')) return
  try {
    const res = await apiFetch(`/positions/${id}`, { method: 'DELETE' })
    if (!res.ok) throw new Error('删除失败')
    await loadData()
  } catch (e: any) {
    alert(e.message || '删除失败')
  }
}

onMounted(loadData)
</script>

<style scoped>
.container {
  max-width: 900px;
  margin: 0 auto;
  padding: 20px 16px;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  flex-wrap: wrap;
  gap: 12px;
}

.header h1 {
  font-size: 1.5rem;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  gap: 8px;
}

.btn {
  padding: 8px 16px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-sync {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border: 1px solid var(--border);
}

.btn-sync:hover:not(:disabled) {
  border-color: var(--accent);
}

.btn-secondary {
  background: var(--bg-tertiary);
  color: var(--text-secondary);
  border: 1px solid var(--border);
}

.btn-icon {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 1.1rem;
  padding: 4px;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.btn-icon:hover {
  opacity: 1;
}

.sync-result {
  padding: 12px 16px;
  border-radius: 8px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 0.9rem;
}

.sync-result.success {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
  color: var(--success);
}

.sync-result.error {
  background: rgba(239, 68, 68, 0.1);
  border: 1px solid rgba(239, 68, 68, 0.3);
  color: var(--danger);
}

.close-btn {
  margin-left: auto;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  font-size: 1.2rem;
}

.loading-state, .error-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  margin: 0 auto 16px;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}

.overview-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  text-align: center;
}

.overview-card .label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 4px;
}

.overview-card .value {
  font-size: 1.3rem;
  font-weight: 600;
}

.overview-card.profit .value {
  color: var(--success);
}

.overview-card.loss .value {
  color: var(--danger);
}

.form-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
  margin-bottom: 24px;
}

.form-card h3 {
  margin-bottom: 16px;
  color: var(--text-primary);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.form-group label {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.form-group input,
.form-group select {
  padding: 10px 12px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 0.9rem;
}

.form-group input:focus,
.form-group select:focus {
  outline: none;
  border-color: var(--accent);
}

.form-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.section {
  margin-top: 24px;
}

.section h2 {
  font-size: 1.1rem;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.empty-state {
  text-align: center;
  padding: 40px;
  color: var(--text-secondary);
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 8px;
}

.position-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.position-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  transition: border-color 0.2s;
}

.position-card:hover {
  border-color: var(--accent);
}

.position-card.closed {
  opacity: 0.5;
}

.position-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.position-name {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-badge {
  font-size: 0.7rem;
  padding: 2px 8px;
  border-radius: 4px;
  font-weight: 500;
}

.type-badge.stock { background: rgba(239, 68, 68, 0.15); color: #EF4444; }
.type-badge.fund { background: rgba(59, 130, 246, 0.15); color: #3B82F6; }
.type-badge.bond { background: rgba(34, 197, 94, 0.15); color: #22C55E; }
.type-badge.wealth_mgmt { background: rgba(168, 85, 247, 0.15); color: #A855F7; }
.type-badge.other { background: rgba(107, 114, 128, 0.15); color: #6B7280; }

.name {
  font-weight: 600;
  font-size: 1rem;
}

.symbol {
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.position-actions {
  display: flex;
  gap: 4px;
}

.position-body {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  padding: 14px 16px;
}

.metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-label {
  font-size: 0.75rem;
  color: var(--text-secondary);
}

.metric-value {
  font-size: 0.9rem;
  font-weight: 500;
}

.text-profit { color: var(--success); }
.text-loss { color: var(--danger); }

.position-footer {
  display: flex;
  justify-content: space-between;
  padding: 8px 16px;
  font-size: 0.75rem;
  color: var(--text-secondary);
  border-top: 1px solid var(--border);
}

@media (max-width: 600px) {
  .position-body {
    grid-template-columns: repeat(2, 1fr);
  }
  .overview {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>

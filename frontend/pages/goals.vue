<template>
  <div class="container">
    <div class="header">
      <h1>财务目标</h1>
      <button @click="showAddForm = !showAddForm" class="btn btn-primary">
        {{ showAddForm ? '取消' : '+ 新建目标' }}
      </button>
    </div>

    <!-- 总览卡片 -->
    <div class="overview">
      <div class="overview-card">
        <div class="label">进行中</div>
        <div class="value">{{ summary.active_goals }}</div>
      </div>
      <div class="overview-card">
        <div class="label">已完成</div>
        <div class="value income">{{ summary.completed_goals }}</div>
      </div>
      <div class="overview-card highlight">
        <div class="label">总进度</div>
        <div class="value">{{ summary.overall_progress.toFixed(1) }}%</div>
      </div>
      <div class="overview-card">
        <div class="label">已积累 / 总目标</div>
        <div class="value">¥{{ formatMoney(summary.total_current) }} / ¥{{ formatMoney(summary.total_target) }}</div>
      </div>
    </div>

    <!-- 新建目标表单 -->
    <div v-if="showAddForm" class="form-card">
      <h3>{{ editingId ? '编辑目标' : '新建目标' }}</h3>
      <form @submit.prevent="handleSubmit">
        <div class="form-grid">
          <div class="form-group">
            <label>目标名称</label>
            <input v-model="form.name" type="text" required placeholder="如：买房首付" />
          </div>
          <div class="form-group">
            <label>类型</label>
            <select v-model="form.goal_type" required>
              <option value="savings">储蓄</option>
              <option value="purchase">购买大件</option>
              <option value="debt_payoff">还债</option>
              <option value="investment">投资增值</option>
            </select>
          </div>
          <div class="form-group">
            <label>目标金额</label>
            <input v-model="form.target_amount" type="number" step="0.01" min="0.01" required placeholder="100000" />
          </div>
          <div class="form-group">
            <label>已积累金额</label>
            <input v-model="form.current_amount" type="number" step="0.01" min="0" placeholder="0" />
          </div>
          <div class="form-group">
            <label>截止日期</label>
            <input v-model="form.deadline" type="date" />
          </div>
          <div class="form-group">
            <label>优先级</label>
            <select v-model="form.priority">
              <option value="high">高</option>
              <option value="medium">中</option>
              <option value="low">低</option>
            </select>
          </div>
          <div class="form-group full">
            <label>备注</label>
            <input v-model="form.notes" type="text" placeholder="可选" />
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">{{ editingId ? '更新' : '创建' }}</button>
          <button type="button" @click="resetForm" class="btn btn-secondary">清空</button>
        </div>
      </form>
    </div>

    <!-- 目标列表 -->
    <div class="goals-list" v-if="summary.goals && summary.goals.length > 0">
      <div
        v-for="goal in summary.goals"
        :key="goal.id"
        class="goal-card"
        :class="{ completed: goal.status === 'completed', abandoned: goal.status === 'abandoned' }"
      >
        <div class="goal-header">
          <div class="goal-info">
            <span class="goal-type-badge" :class="goal.goal_type">{{ typeLabel(goal.goal_type) }}</span>
            <h3>{{ goal.name }}</h3>
            <span class="priority-badge" :class="goal.priority">{{ priorityLabel(goal.priority) }}</span>
          </div>
          <div class="goal-actions">
            <button @click="openContribute(goal)" class="btn btn-sm btn-primary" v-if="goal.status === 'active'">投入</button>
            <button @click="startEdit(goal)" class="btn btn-sm btn-secondary">编辑</button>
            <button @click="handleDelete(goal)" class="btn btn-sm btn-danger">删除</button>
          </div>
        </div>

        <div class="goal-progress">
          <div class="progress-bar">
            <div
              class="progress-fill"
              :class="{ completed: goal.progress_percent >= 100 }"
              :style="{ width: Math.min(goal.progress_percent, 100) + '%' }"
            ></div>
          </div>
          <div class="progress-info">
            <span>¥{{ formatMoney(goal.current_amount) }} / ¥{{ formatMoney(goal.target_amount) }}</span>
            <span class="progress-percent">{{ goal.progress_percent.toFixed(1) }}%</span>
          </div>
        </div>

        <div class="goal-meta" v-if="goal.deadline || goal.notes">
          <span v-if="goal.deadline" class="meta-item">📅 {{ goal.deadline }}</span>
          <span v-if="goal.notes" class="meta-item">{{ goal.notes }}</span>
        </div>
      </div>
    </div>

    <div v-else-if="!loading" class="empty-state">
      <p>还没有设定财务目标</p>
      <p class="hint">设定目标后，可以追踪每笔投入的进度</p>
    </div>

    <!-- 投入弹窗 -->
    <div v-if="contributeGoal" class="modal-overlay" @click.self="contributeGoal = null">
      <div class="modal">
        <h3>投入「{{ contributeGoal.name }}」</h3>
        <p class="modal-hint">当前进度：{{ contributeGoal.progress_percent.toFixed(1) }}%</p>
        <form @submit.prevent="handleContribute">
          <div class="form-group">
            <label>投入金额</label>
            <input v-model="contributeAmount" type="number" step="0.01" min="0.01" required placeholder="1000" autofocus />
          </div>
          <div class="form-group">
            <label>备注（可选）</label>
            <input v-model="contributeDesc" type="text" placeholder="如：本月工资存入" />
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary">确认投入</button>
            <button type="button" @click="contributeGoal = null" class="btn btn-secondary">取消</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import {
  fetchGoalsSummary, createGoal, updateGoal, deleteGoal, contributeToGoal
} from '~/utils/api'

const summary = ref({
  total_goals: 0, active_goals: 0, completed_goals: 0,
  total_target: 0, total_current: 0, overall_progress: 0, goals: []
})
const loading = ref(true)
const showAddForm = ref(false)
const editingId = ref(null)

const defaultForm = {
  name: '', goal_type: 'savings', target_amount: null, current_amount: 0,
  deadline: '', priority: 'medium', notes: ''
}
const form = ref({ ...defaultForm })

// 投入弹窗
const contributeGoal = ref(null)
const contributeAmount = ref(null)
const contributeDesc = ref('')

const typeLabels = { savings: '储蓄', purchase: '购买', debt_payoff: '还债', investment: '投资' }
const priorityLabels = { high: '高优先', medium: '中优先', low: '低优先' }
const typeLabel = (t) => typeLabels[t] || t
const priorityLabel = (p) => priorityLabels[p] || p

const formatMoney = (v) => {
  if (!v && v !== 0) return '0.00'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function loadData() {
  loading.value = true
  try {
    summary.value = await fetchGoalsSummary()
  } catch (e) {
    console.error('Failed to load goals:', e)
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  try {
    const data = { ...form.value }
    if (!data.deadline) delete data.deadline
    if (editingId.value) {
      await updateGoal(editingId.value, data)
    } else {
      await createGoal(data)
    }
    resetForm()
    await loadData()
  } catch (e) {
    alert('操作失败: ' + e.message)
  }
}

function startEdit(goal) {
  editingId.value = goal.id
  form.value = {
    name: goal.name,
    goal_type: goal.goal_type,
    target_amount: goal.target_amount,
    current_amount: goal.current_amount,
    deadline: goal.deadline || '',
    priority: goal.priority,
    notes: goal.notes || ''
  }
  showAddForm.value = true
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetForm() {
  form.value = { ...defaultForm }
  editingId.value = null
  showAddForm.value = false
}

async function handleDelete(goal) {
  if (!confirm(`确定删除目标「${goal.name}」？所有投入记录也会被删除。`)) return
  try {
    await deleteGoal(goal.id)
    await loadData()
  } catch (e) {
    alert('删除失败: ' + e.message)
  }
}

function openContribute(goal) {
  contributeGoal.value = goal
  contributeAmount.value = null
  contributeDesc.value = ''
}

async function handleContribute() {
  if (!contributeAmount.value || contributeAmount.value <= 0) return
  try {
    await contributeToGoal(contributeGoal.value.id, contributeAmount.value, contributeDesc.value || undefined)
    contributeGoal.value = null
    await loadData()
  } catch (e) {
    alert('投入失败: ' + e.message)
  }
}

onMounted(loadData)
</script>

<style scoped>
.container {
  max-width: 900px;
  margin: 0 auto;
  padding: 2rem 1.5rem;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.header h1 {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.overview {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.overview-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.2rem;
}

.overview-card.highlight {
  border-color: var(--accent);
  background: var(--accent-glow);
}

.overview-card .label {
  font-size: 0.8rem;
  color: var(--text-secondary);
  margin-bottom: 0.4rem;
}

.overview-card .value {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary);
}

.overview-card .value.income { color: #22c55e; }

.form-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 2rem;
}

.form-card h3 {
  margin-bottom: 1rem;
  color: var(--text-primary);
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

.form-group.full { grid-column: 1 / -1; }

.form-group label {
  font-size: 0.85rem;
  color: var(--text-secondary);
  font-weight: 500;
}

.form-group input,
.form-group select {
  padding: 0.6rem 0.8rem;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 0.9rem;
}

.form-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: 1rem;
}

.goals-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.goal-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.2rem;
  transition: border-color 0.15s;
}

.goal-card:hover { border-color: var(--accent); }
.goal-card.completed { opacity: 0.7; border-color: #22c55e; }
.goal-card.abandoned { opacity: 0.5; }

.goal-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 1rem;
}

.goal-info {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  flex-wrap: wrap;
}

.goal-info h3 {
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.goal-type-badge {
  font-size: 0.75rem;
  padding: 0.2rem 0.5rem;
  border-radius: 6px;
  font-weight: 500;
}

.goal-type-badge.savings { background: #22c55e20; color: #22c55e; }
.goal-type-badge.purchase { background: #3b82f620; color: #3b82f6; }
.goal-type-badge.debt_payoff { background: #f59e0b20; color: #f59e0b; }
.goal-type-badge.investment { background: #8b5cf620; color: #8b5cf6; }

.priority-badge {
  font-size: 0.7rem;
  padding: 0.15rem 0.4rem;
  border-radius: 4px;
}

.priority-badge.high { background: #ef444420; color: #ef4444; }
.priority-badge.medium { background: #f59e0b20; color: #f59e0b; }
.priority-badge.low { background: #6b728020; color: #6b7280; }

.goal-actions {
  display: flex;
  gap: 0.4rem;
}

.goal-progress { margin-bottom: 0.8rem; }

.progress-bar {
  height: 8px;
  background: var(--bg-tertiary, rgba(255,255,255,0.05));
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 0.4rem;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), #60a5fa);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-fill.completed {
  background: linear-gradient(90deg, #22c55e, #4ade80);
}

.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.progress-percent {
  font-weight: 600;
  color: var(--accent);
}

.goal-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--text-secondary);
}

.empty-state {
  text-align: center;
  padding: 3rem;
  color: var(--text-secondary);
}

.empty-state .hint {
  font-size: 0.85rem;
  margin-top: 0.5rem;
  opacity: 0.7;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.modal {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 1.5rem;
  width: 90%;
  max-width: 400px;
}

.modal h3 {
  margin-bottom: 0.3rem;
  color: var(--text-primary);
}

.modal-hint {
  font-size: 0.85rem;
  color: var(--text-secondary);
  margin-bottom: 1rem;
}

/* Buttons */
.btn {
  padding: 0.5rem 1rem;
  border-radius: 8px;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.15s;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
}

.btn-primary:hover { opacity: 0.9; }

.btn-secondary {
  background: var(--bg-tertiary, rgba(255,255,255,0.1));
  color: var(--text-primary);
}

.btn-danger {
  background: #ef444420;
  color: #ef4444;
}

.btn-sm {
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
}

@media (max-width: 640px) {
  .form-grid { grid-template-columns: 1fr; }
  .goal-header { flex-direction: column; gap: 0.8rem; }
  .overview { grid-template-columns: 1fr 1fr; }
}
</style>

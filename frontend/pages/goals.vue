<template>
  <div class="mx-auto min-w-0 w-full max-w-4xl px-4 py-6">
    <!-- 页头 -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="mr-auto min-w-0">
        <h1 class="text-xl font-semibold" style="color: var(--text-primary)">财务目标</h1>
        <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">先定一个数，再一笔一笔往里放。</p>
      </div>
      <UButton @click="showAddForm = !showAddForm">
        <AppIcon :icon="showAddForm ? 'X' : 'Plus'" :size="15" />
        {{ showAddForm ? '取消' : '新建目标' }}
      </UButton>
    </div>

    <!-- 操作失败提示（替代 alert） -->
    <UAlert
      v-if="actionError"
      color="error"
      variant="soft"
      :title="actionError"
      class="mt-4"
      close
      @update:open="actionError = ''"
    />

    <!-- 加载中：骨架 -->
    <div v-if="loading" class="mt-4 space-y-4">
      <div class="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <USkeleton v-for="i in 4" :key="i" class="h-[76px] w-full" />
      </div>
      <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
        <USkeleton class="h-5 w-40" />
        <USkeleton class="mt-3 h-2.5 w-full" />
        <USkeleton class="mt-2 h-4 w-2/3" />
      </UCard>
    </div>

    <template v-else>
      <!-- 总览卡片 -->
      <div class="mt-4 grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4' }">
          <div class="text-xs" style="color: var(--text-secondary)">进行中</div>
          <div class="mt-1 text-2xl font-bold tabular-nums" style="color: var(--text-primary)">{{ summary.active_goals }}</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4' }">
          <div class="text-xs" style="color: var(--text-secondary)">已完成</div>
          <div class="mt-1 text-2xl font-bold tabular-nums" style="color: var(--success)">{{ summary.completed_goals }}</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4' }">
          <div class="text-xs" style="color: var(--text-secondary)">总进度</div>
          <div class="mt-1 text-2xl font-bold tabular-nums" style="color: var(--accent)">{{ summary.overall_progress.toFixed(1) }}%</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4' }">
          <div class="text-xs" style="color: var(--text-secondary)">已积累 / 总目标</div>
          <div class="mt-1 truncate text-lg font-bold tabular-nums" style="color: var(--text-primary)">¥{{ formatMoney(summary.total_current) }} / ¥{{ formatMoney(summary.total_target) }}</div>
        </UCard>
      </div>

      <!-- 新建/编辑目标表单 -->
      <UCard
        v-if="showAddForm"
        class="mt-4"
        :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
        :ui="{ body: 'p-5' }"
      >
        <h3 class="mb-3 text-base font-semibold" style="color: var(--text-primary)">{{ editingId ? '编辑目标' : '新建目标' }}</h3>
        <form @submit.prevent="handleSubmit">
          <div class="grid grid-cols-1 gap-3 min-[480px]:grid-cols-2">
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-name">目标名称</label>
              <UInput id="goal-name" v-model="form.name" type="text" required placeholder="如：买房首付" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-type">类型</label>
              <USelect id="goal-type" v-model="form.goal_type" :items="goalTypeItems" value-key="value" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-target">目标金额</label>
              <UInput id="goal-target" v-model="form.target_amount" type="number" step="0.01" min="0.01" required placeholder="100000" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-current">已积累金额</label>
              <UInput id="goal-current" v-model="form.current_amount" type="number" step="0.01" min="0" placeholder="0" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-deadline">截止日期</label>
              <UInput id="goal-deadline" v-model="form.deadline" type="date" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-priority">优先级</label>
              <USelect id="goal-priority" v-model="form.priority" :items="priorityItems" value-key="value" class="w-full" />
            </div>
            <div class="min-w-0 min-[480px]:col-span-2">
              <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="goal-notes">备注</label>
              <UInput id="goal-notes" v-model="form.notes" type="text" placeholder="可选" class="w-full" />
            </div>
          </div>
          <div class="mt-4 flex flex-wrap gap-2">
            <UButton type="submit">{{ editingId ? '更新' : '创建' }}</UButton>
            <UButton type="button" variant="outline" color="neutral" @click="resetForm">清空</UButton>
          </div>
        </form>
      </UCard>

      <!-- 目标列表 -->
      <div v-if="summary.goals && summary.goals.length > 0" class="mt-4 space-y-3">
        <UCard
          v-for="goal in summary.goals"
          :key="goal.id"
          class="relative"
          :style="{
            background: 'var(--bg-secondary)',
            border: goal.status === 'completed' ? '1px solid var(--success)' : '1px solid var(--border)',
            opacity: goal.status === 'abandoned' ? 0.55 : goal.status === 'completed' ? 0.85 : 1,
          }"
          :ui="{ body: 'p-4' }"
        >
          <!-- 达成庆祝：100% 只出现一次，450ms 对勾，纯 CSS -->
          <div v-if="celebratingId === goal.id" class="celebrate" role="status" aria-label="目标达成">
            <span class="celebrate-ring">
              <AppIcon icon="Check" :size="26" />
            </span>
          </div>
          <div class="flex flex-wrap items-start justify-between gap-2">
            <div class="flex min-w-0 flex-wrap items-center gap-2">
              <UBadge :color="goalTypeColor(goal.goal_type)" variant="soft">{{ typeLabel(goal.goal_type) }}</UBadge>
              <h3 class="text-base font-semibold" style="color: var(--text-primary)">{{ goal.name }}</h3>
              <UBadge :color="priorityColor(goal.priority)" variant="soft">{{ priorityLabel(goal.priority) }}</UBadge>
              <UBadge v-if="goal.status === 'completed'" color="success" variant="soft">已完成</UBadge>
            </div>
            <div class="flex shrink-0 flex-wrap gap-1.5">
              <UButton v-if="goal.status === 'active'" size="xs" @click="openContribute(goal)">投入</UButton>
              <UButton size="xs" variant="outline" color="neutral" @click="startEdit(goal)">编辑</UButton>
              <UButton size="xs" variant="outline" color="error" @click="pendingDelete = goal">删除</UButton>
            </div>
          </div>

          <div class="mt-3">
            <UProgress :model-value="Math.min(goal.progress_percent, 100)" :max="100" :color="goal.progress_percent >= 100 ? 'success' : 'primary'" />
            <div class="mt-1.5 flex items-center justify-between text-xs tabular-nums">
              <span style="color: var(--text-secondary)">¥{{ formatMoney(goal.current_amount) }} / ¥{{ formatMoney(goal.target_amount) }}</span>
              <span class="font-semibold" style="color: var(--accent)">{{ goal.progress_percent.toFixed(1) }}%</span>
            </div>
          </div>

          <div v-if="goal.deadline || goal.notes" class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs" style="color: var(--text-secondary)">
            <span v-if="goal.deadline" class="inline-flex items-center gap-1 tabular-nums"><AppIcon icon="CalendarBlank" :size="14" /> {{ goal.deadline }}</span>
            <span v-if="goal.notes">{{ goal.notes }}</span>
          </div>
        </UCard>
      </div>

      <!-- 空状态 -->
      <UCard
        v-else
        class="mt-4 text-center"
        :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
        :ui="{ body: 'p-8' }"
      >
        <AppIcon icon="PiggyBank" :size="32" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="mt-3 text-sm font-medium" style="color: var(--text-primary)">还没有设定财务目标</p>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">定一个数，之后每笔投入都能看到进度。</p>
        <UButton class="mt-4" @click="showAddForm = true">新建目标</UButton>
      </UCard>
    </template>

    <!-- 投入弹窗 -->
    <UModal :open="!!contributeGoal" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }" @update:open="(v) => { if (!v) contributeGoal = null }">
      <template #content>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" style="color: var(--text-primary)">投入「{{ contributeGoal?.name }}」</h3>
          <p class="mb-3 mt-1 text-xs tabular-nums" style="color: var(--text-secondary)">当前进度：{{ contributeGoal?.progress_percent.toFixed(1) }}%</p>
          <form @submit.prevent="handleContribute">
            <div class="space-y-3">
              <div>
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="contribute-amount">投入金额</label>
                <UInput id="contribute-amount" v-model="contributeAmount" type="number" step="0.01" min="0.01" required placeholder="1000" autofocus class="w-full" />
              </div>
              <div>
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="contribute-desc">备注（可选）</label>
                <UInput id="contribute-desc" v-model="contributeDesc" type="text" placeholder="如：本月工资存入" class="w-full" />
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <UButton type="submit">确认投入</UButton>
              <UButton type="button" variant="outline" color="neutral" @click="contributeGoal = null">取消</UButton>
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- 删除确认（替代 confirm） -->
    <UModal :open="!!pendingDelete" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }" @update:open="(v) => { if (!v) pendingDelete = null }">
      <template #content>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" style="color: var(--text-primary)">删除目标</h3>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">确定删除「{{ pendingDelete?.name }}」？所有投入记录也会被删除。</p>
          <div class="mt-4 flex flex-wrap gap-2">
            <UButton color="error" @click="confirmDelete">确认删除</UButton>
            <UButton variant="outline" color="neutral" @click="pendingDelete = null">取消</UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated } from 'vue'
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
const actionError = ref('')

const defaultForm = {
  name: '', goal_type: 'savings', target_amount: null, current_amount: 0,
  deadline: '', priority: 'medium', notes: ''
}
const form = ref({ ...defaultForm })

const goalTypeItems = [
  { label: '储蓄', value: 'savings' },
  { label: '购买大件', value: 'purchase' },
  { label: '还债', value: 'debt_payoff' },
  { label: '投资增值', value: 'investment' },
]
const priorityItems = [
  { label: '高', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低', value: 'low' },
]

// 投入弹窗
const contributeGoal = ref(null)
const contributeAmount = ref(null)
const contributeDesc = ref('')

// 删除确认（替代 confirm）
const pendingDelete = ref(null)

// 达成庆祝：每个目标只庆祝一次，记录在客户端 localStorage
const CELEBRATED_KEY = 'sb-goals-celebrated'
const celebratingId = ref(null)
const readCelebrated = () => {
  if (!import.meta.client) return []
  try {
    const raw = JSON.parse(localStorage.getItem(CELEBRATED_KEY) || '[]')
    return Array.isArray(raw) ? raw : []
  } catch { return [] }
}
const markCelebrated = (ids) => {
  if (!import.meta.client) return
  try {
    const merged = Array.from(new Set([...readCelebrated(), ...ids]))
    localStorage.setItem(CELEBRATED_KEY, JSON.stringify(merged))
  } catch {}
}
const maybeCelebrate = () => {
  const done = readCelebrated()
  const fresh = (summary.value.goals || []).filter(
    (g) => g.progress_percent >= 100 && !done.includes(g.id)
  )
  if (!fresh.length) return
  celebratingId.value = fresh[0].id
  markCelebrated(fresh.map((g) => g.id))
  setTimeout(() => { celebratingId.value = null }, 450)
}

const typeLabels = { savings: '储蓄', purchase: '购买', debt_payoff: '还债', investment: '投资' }
const priorityLabels = { high: '高优先', medium: '中优先', low: '低优先' }
const typeLabel = (t) => typeLabels[t] || t
const priorityLabel = (p) => priorityLabels[p] || p
const goalTypeColor = (t) => {
  if (t === 'savings') return 'success'
  if (t === 'purchase') return 'info'
  if (t === 'debt_payoff') return 'warning'
  if (t === 'investment') return 'primary'
  return 'neutral'
}
const priorityColor = (p) => {
  if (p === 'high') return 'error'
  if (p === 'medium') return 'warning'
  return 'neutral'
}

const formatMoney = (v) => {
  if (!v && v !== 0) return '0.00'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

async function loadData() {
  loading.value = true
  try {
    summary.value = await fetchGoalsSummary()
    maybeCelebrate()
  } catch (e) {
    console.error('Failed to load goals:', e)
  } finally {
    loading.value = false
  }
}

async function handleSubmit() {
  actionError.value = ''
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
    actionError.value = '保存失败：' + e.message
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

async function confirmDelete() {
  if (!pendingDelete.value) return
  try {
    await deleteGoal(pendingDelete.value.id)
    pendingDelete.value = null
    await loadData()
  } catch (e) {
    pendingDelete.value = null
    actionError.value = '删除失败：' + e.message
  }
}

function openContribute(goal) {
  contributeGoal.value = goal
  contributeAmount.value = null
  contributeDesc.value = ''
}

async function handleContribute() {
  if (!contributeAmount.value || contributeAmount.value <= 0) return
  actionError.value = ''
  try {
    await contributeToGoal(contributeGoal.value.id, contributeAmount.value, contributeDesc.value || undefined)
    contributeGoal.value = null
    await loadData()
  } catch (e) {
    actionError.value = '投入失败：' + e.message
  }
}

onMounted(loadData)
onActivated(loadData)
</script>

<style scoped>
/* 达成庆祝：对勾弹入 + 光环扩散，450ms 内收尾，纯 CSS 无库 */
.celebrate {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
  z-index: 10;
}
.celebrate-ring {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: 9999px;
  color: var(--accent-ink);
  background: var(--success);
  animation: celebrate-pop 450ms cubic-bezier(0.16, 1, 0.3, 1) both;
}
@keyframes celebrate-pop {
  0% { opacity: 0; transform: scale(0.4); box-shadow: 0 0 0 0 var(--success-soft); }
  55% { opacity: 1; transform: scale(1.08); box-shadow: 0 0 0 14px var(--success-soft); }
  100% { opacity: 1; transform: scale(1); box-shadow: 0 0 0 0 transparent; }
}

@media (prefers-reduced-motion: reduce) {
  .celebrate-ring {
    animation: none;
  }
}
</style>

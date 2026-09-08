<template>
  <div class="mx-auto min-w-0 w-full max-w-5xl px-4 py-6">
    <!-- 页头 -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="mr-auto min-w-0">
        <h1 class="text-xl font-semibold" style="color: var(--text-primary)">投资持仓</h1>
        <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">放在场内的钱，现在值多少。</p>
      </div>
      <UButton variant="outline" color="neutral" :loading="syncing" :disabled="syncing" @click="syncPositions">
        <AppIcon v-if="!syncing" icon="ArrowClockwise" :size="15" />
        {{ syncing ? '同步中...' : '同步持仓' }}
      </UButton>
      <UButton @click="toggleAddForm">
        <AppIcon :icon="showAddForm ? 'X' : 'Plus'" :size="15" />
        {{ showAddForm ? '取消' : '添加持仓' }}
      </UButton>
    </div>

    <!-- 同步结果（替代裸文字条） -->
    <UAlert
      v-if="syncResult"
      :color="syncResult.error ? 'error' : 'success'"
      variant="soft"
      :title="syncResult.message"
      :description="syncDetail"
      class="mt-4"
      close
      @update:open="syncResult = null"
    />

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
      <USkeleton class="h-[320px] w-full" />
    </div>

    <!-- 加载失败 -->
    <UCard
      v-else-if="loadError"
      class="mt-4 text-center"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-8' }"
    >
      <AppIcon icon="Warning" :size="28" style="color: var(--danger)" class="mx-auto" />
      <p class="mt-2 text-sm" style="color: var(--text-primary)">{{ loadError }}</p>
      <UButton class="mt-4" @click="loadData">重试</UButton>
    </UCard>

    <template v-else>
      <!-- 总览卡片 -->
      <div class="mt-4 grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4 text-center' }">
          <div class="text-xs" style="color: var(--text-secondary)">总市值</div>
          <div class="mt-1 text-xl font-bold tabular-nums" style="color: var(--text-primary)">¥{{ formatNum(summary.total_value) }}</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4 text-center' }">
          <div class="text-xs" style="color: var(--text-secondary)">总成本</div>
          <div class="mt-1 text-xl font-bold tabular-nums" style="color: var(--text-primary)">¥{{ formatNum(summary.total_cost) }}</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4 text-center' }">
          <div class="text-xs" style="color: var(--text-secondary)">总收益</div>
          <div class="mt-1 text-xl font-bold tabular-nums" :style="{ color: summary.total_profit >= 0 ? 'var(--success)' : 'var(--danger)' }">{{ summary.total_profit >= 0 ? '+' : '' }}¥{{ formatNum(summary.total_profit) }}</div>
        </UCard>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-4 text-center' }">
          <div class="text-xs" style="color: var(--text-secondary)">收益率</div>
          <div class="mt-1 text-xl font-bold tabular-nums" :style="{ color: summary.total_profit_pct >= 0 ? 'var(--success)' : 'var(--danger)' }">{{ summary.total_profit_pct >= 0 ? '+' : '' }}{{ summary.total_profit_pct.toFixed(2) }}%</div>
        </UCard>
      </div>

      <!-- 持仓明细 -->
      <UCard
        class="mt-4"
        :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
        :ui="{ body: 'p-4 min-[480px]:p-5' }"
      >
        <div class="mb-3 flex flex-wrap items-center gap-2">
          <h2 class="mr-auto text-base font-semibold tabular-nums" style="color: var(--text-primary)">持仓明细 ({{ filteredPositions.length }}/{{ positions.length }})</h2>
        </div>

        <!-- 筛选栏（条件记在客户端 localStorage） -->
        <div class="mb-3 flex flex-wrap gap-2">
          <UInput v-model="positionSearch" type="text" placeholder="搜索名称/代码..." aria-label="搜索持仓" class="min-w-[150px] flex-1" />
          <USelect v-model="positionTypeFilter" :items="typeFilterItems" value-key="value" aria-label="按类型筛选" class="w-32" />
          <USelect v-model="positionAccountFilter" :items="accountFilterItems" value-key="value" aria-label="按账户筛选" class="w-36" />
          <USelect v-model="positionStatusFilter" :items="statusFilterItems" value-key="value" aria-label="按状态筛选" class="w-28" />
        </div>

        <!-- 空状态 -->
        <div v-if="sortedPositions.length === 0" class="py-10 text-center">
          <AppIcon icon="ChartPieSlice" :size="32" style="color: var(--text-tertiary)" class="mx-auto" />
          <p class="mt-3 text-sm font-medium" style="color: var(--text-primary)">暂无投资持仓</p>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">点右上角「添加持仓」，把第一笔记下来。</p>
          <UButton class="mt-4" @click="showAddForm = true">添加持仓</UButton>
        </div>

        <!-- 桌面端表格（带排序） -->
        <div v-else class="hidden md:block">
          <UTable v-model:sorting="sorting" :data="sortedPositions" :columns="columns" empty="暂无符合条件的持仓">
            <template #name-cell="{ row }">
              <div class="flex min-w-0 items-center gap-2">
                <UBadge :color="positionTypeColor(row.original.position_type)" variant="soft">{{ typeLabel(row.original.position_type) }}</UBadge>
                <span class="truncate font-medium" style="color: var(--text-primary)">{{ row.original.name }}</span>
                <span v-if="row.original.symbol" class="shrink-0 text-xs" style="color: var(--text-secondary)">{{ row.original.symbol }}</span>
                <UBadge v-if="row.original.status === 'closed'" color="neutral" variant="soft">已关闭</UBadge>
              </div>
            </template>
            <template #quantity-cell="{ row }">
              <span class="tabular-nums">{{ row.original.quantity }}</span>
            </template>
            <template #avg_cost-cell="{ row }">
              <span class="tabular-nums">¥{{ formatNum(row.original.avg_cost) }}</span>
            </template>
            <template #current_price-cell="{ row }">
              <span class="tabular-nums">¥{{ formatNum(row.original.current_price) }}</span>
            </template>
            <template #market_value-cell="{ row }">
              <span class="font-medium tabular-nums">¥{{ formatNum(row.original.market_value) }}</span>
            </template>
            <template #profit-cell="{ row }">
              <span class="font-medium tabular-nums" :style="{ color: row.original.profit >= 0 ? 'var(--success)' : 'var(--danger)' }">
                {{ row.original.profit >= 0 ? '+' : '' }}¥{{ formatNum(row.original.profit) }}
              </span>
            </template>
            <template #profit_pct-cell="{ row }">
              <span class="font-medium tabular-nums" :style="{ color: row.original.profit_pct >= 0 ? 'var(--success)' : 'var(--danger)' }">
                {{ row.original.profit_pct >= 0 ? '+' : '' }}{{ row.original.profit_pct.toFixed(2) }}%
              </span>
            </template>
            <template #account-cell="{ row }">
              <div class="text-xs">
                <div v-if="row.original.account" style="color: var(--text-primary)">{{ row.original.account }}</div>
                <div v-if="row.original.updated_at" class="tabular-nums" style="color: var(--text-secondary)">更新于 {{ formatTime(row.original.updated_at) }}</div>
              </div>
            </template>
            <template #actions-cell="{ row }">
              <div class="flex justify-end gap-1">
                <UButton size="xs" variant="ghost" color="neutral" square aria-label="编辑持仓" @click="editPosition(row.original)">
                  <AppIcon icon="PencilSimple" :size="16" />
                </UButton>
                <UButton size="xs" variant="ghost" color="error" square aria-label="关闭持仓" @click="pendingDelete = row.original">
                  <AppIcon icon="Trash" :size="16" />
                </UButton>
              </div>
            </template>
          </UTable>
        </div>

        <!-- 移动端卡片 -->
        <div v-if="sortedPositions.length > 0" class="space-y-2.5 md:hidden">
          <div
            v-for="pos in sortedPositions"
            :key="pos.id"
            class="rounded-lg p-3.5"
            :style="{ background: 'var(--bg-primary)', border: '1px solid var(--border)', opacity: pos.status === 'closed' ? 0.6 : 1 }"
          >
            <div class="flex items-center justify-between gap-2">
              <div class="flex min-w-0 items-center gap-2">
                <UBadge :color="positionTypeColor(pos.position_type)" variant="soft">{{ typeLabel(pos.position_type) }}</UBadge>
                <span class="truncate text-sm font-semibold" style="color: var(--text-primary)">{{ pos.name }}</span>
                <span v-if="pos.symbol" class="shrink-0 text-xs" style="color: var(--text-secondary)">{{ pos.symbol }}</span>
              </div>
              <div class="flex shrink-0 gap-1">
                <UButton size="xs" variant="ghost" color="neutral" square aria-label="编辑持仓" @click="editPosition(pos)">
                  <AppIcon icon="PencilSimple" :size="16" />
                </UButton>
                <UButton size="xs" variant="ghost" color="error" square aria-label="关闭持仓" @click="pendingDelete = pos">
                  <AppIcon icon="Trash" :size="16" />
                </UButton>
              </div>
            </div>
            <div class="mt-2.5 grid grid-cols-3 gap-2">
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">持有数量</div>
                <div class="text-sm font-medium tabular-nums" style="color: var(--text-primary)">{{ pos.quantity }}</div>
              </div>
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">买入均价</div>
                <div class="text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ formatNum(pos.avg_cost) }}</div>
              </div>
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">当前价格</div>
                <div class="text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ formatNum(pos.current_price) }}</div>
              </div>
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">市值</div>
                <div class="text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ formatNum(pos.market_value) }}</div>
              </div>
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">收益</div>
                <div class="text-sm font-medium tabular-nums" :style="{ color: pos.profit >= 0 ? 'var(--success)' : 'var(--danger)' }">{{ pos.profit >= 0 ? '+' : '' }}¥{{ formatNum(pos.profit) }}</div>
              </div>
              <div>
                <div class="text-[11px]" style="color: var(--text-secondary)">收益率</div>
                <div class="text-sm font-medium tabular-nums" :style="{ color: pos.profit_pct >= 0 ? 'var(--success)' : 'var(--danger)' }">{{ pos.profit_pct >= 0 ? '+' : '' }}{{ pos.profit_pct.toFixed(2) }}%</div>
              </div>
            </div>
            <div v-if="pos.account || pos.updated_at" class="mt-2 flex items-center justify-between border-t pt-2 text-[11px]" style="border-color: var(--border); color: var(--text-secondary)">
              <span v-if="pos.account" class="inline-flex items-center gap-1"><AppIcon icon="MapPin" :size="13" /> {{ pos.account }}</span>
              <span v-if="pos.updated_at" class="tabular-nums">更新于 {{ formatTime(pos.updated_at) }}</span>
            </div>
          </div>
        </div>
      </UCard>
    </template>

    <!-- 添加/编辑持仓弹窗 -->
    <UModal v-model:open="showAddForm" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-lg' }">
      <template #content>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
          <h3 class="mb-3 text-base font-semibold" style="color: var(--text-primary)">{{ editingId ? '编辑持仓' : '添加持仓' }}</h3>
          <form @submit.prevent="handleSubmit">
            <div class="grid grid-cols-1 gap-3 min-[480px]:grid-cols-2">
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-name">名称</label>
                <UInput id="pos-name" v-model="form.name" type="text" required placeholder="如：沪深300ETF" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-symbol">代码</label>
                <UInput id="pos-symbol" v-model="form.symbol" type="text" placeholder="如：510300" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-type">类型</label>
                <USelect id="pos-type" v-model="form.position_type" :items="positionTypeItems" value-key="value" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-qty">持有数量</label>
                <UInput id="pos-qty" v-model="form.quantity" type="number" step="0.01" required placeholder="股/份" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-cost">买入均价</label>
                <UInput id="pos-cost" v-model="form.avg_cost" type="number" step="0.0001" required placeholder="成本价" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-price">当前价格</label>
                <UInput id="pos-price" v-model="form.current_price" type="number" step="0.0001" placeholder="留空同步后自动更新" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-account">所属账户</label>
                <UInput id="pos-account" v-model="form.account" type="text" placeholder="如：东方财富证券" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="pos-notes">备注</label>
                <UInput id="pos-notes" v-model="form.notes" type="text" placeholder="可选" class="w-full" />
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <UButton type="submit" :loading="submitting" :disabled="submitting">
                {{ submitting ? '提交中...' : (editingId ? '保存' : '添加') }}
              </UButton>
              <UButton type="button" variant="outline" color="neutral" @click="resetForm">重置</UButton>
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- 关闭持仓确认（替代 confirm） -->
    <UModal :open="!!pendingDelete" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }" @update:open="(v) => { if (!v) pendingDelete = null }">
      <template #content>
        <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" style="color: var(--text-primary)">关闭持仓</h3>
          <p class="mt-1 text-sm" style="color: var(--text-secondary)">确认关闭「{{ pendingDelete?.name }}」？</p>
          <div class="mt-4 flex flex-wrap gap-2">
            <UButton color="error" @click="confirmDeletePosition">确认关闭</UButton>
            <UButton variant="outline" color="neutral" @click="pendingDelete = null">取消</UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import {
  fetchPositionsData,
  createPositionApi,
  updatePositionApi,
  deletePositionApi,
  syncPositionsApi,
} from '~/utils/api'

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
const actionError = ref('')
const positions = ref<Position[]>([])

// 筛选条件：记住上次的选择（客户端 localStorage）
const INVEST_FILTERS_KEY = 'sb-invest-filters'
const readSavedFilters = () => {
  if (!import.meta.client) return { q: '', t: '', a: '', s: '' }
  try {
    const raw = JSON.parse(localStorage.getItem(INVEST_FILTERS_KEY) || '{}')
    return { q: raw.q || '', t: raw.t || '', a: raw.a || '', s: raw.s || '' }
  } catch { return { q: '', t: '', a: '', s: '' } }
}
const savedFilters = readSavedFilters()
const positionSearch = ref(savedFilters.q)
const positionTypeFilter = ref(savedFilters.t)
const positionAccountFilter = ref(savedFilters.a)
const positionStatusFilter = ref(savedFilters.s)
watch([positionSearch, positionTypeFilter, positionAccountFilter, positionStatusFilter], () => {
  if (!import.meta.client) return
  try {
    localStorage.setItem(INVEST_FILTERS_KEY, JSON.stringify({
      q: positionSearch.value, t: positionTypeFilter.value,
      a: positionAccountFilter.value, s: positionStatusFilter.value,
    }))
  } catch {}
})

const uniqueAccounts = computed(() => {
  const accounts = new Set(positions.value.map(p => p.account).filter(Boolean))
  return Array.from(accounts).sort()
})

const typeFilterItems = [
  { label: '全部类型', value: '' },
  { label: '股票', value: 'stock' },
  { label: '基金', value: 'fund' },
  { label: '债券', value: 'bond' },
  { label: '银行理财', value: 'wealth_mgmt' },
  { label: '其他', value: 'other' },
]
const accountFilterItems = computed(() => [
  { label: '全部账户', value: '' },
  ...uniqueAccounts.value.map((a) => ({ label: a as string, value: a as string })),
])
const statusFilterItems = [
  { label: '全部状态', value: '' },
  { label: '活跃', value: 'active' },
  { label: '已关闭', value: 'closed' },
]
const positionTypeItems = [
  { label: '股票', value: 'stock' },
  { label: '基金', value: 'fund' },
  { label: '债券', value: 'bond' },
  { label: '银行理财', value: 'wealth_mgmt' },
  { label: '其他', value: 'other' },
]

const filteredPositions = computed(() => {
  return positions.value.filter(p => {
    if (positionSearch.value) {
      const search = positionSearch.value.toLowerCase()
      if (!p.name.toLowerCase().includes(search) &&
          !(p.symbol && p.symbol.toLowerCase().includes(search))) {
        return false
      }
    }
    if (positionTypeFilter.value && p.position_type !== positionTypeFilter.value) return false
    if (positionAccountFilter.value && p.account !== positionAccountFilter.value) return false
    if (positionStatusFilter.value && p.status !== positionStatusFilter.value) return false
    return true
  })
})

// 表格排序：点表头切换升/降序
const sorting = ref<{ id: string; desc: boolean }[]>([])
const sortedPositions = computed(() => {
  const list = [...filteredPositions.value]
  const s = sorting.value[0]
  if (!s) return list
  const dir = s.desc ? -1 : 1
  return list.sort((a, b) => {
    const av = (a as unknown as Record<string, unknown>)[s.id]
    const bv = (b as unknown as Record<string, unknown>)[s.id]
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    return String(av ?? '').localeCompare(String(bv ?? ''), 'zh-CN') * dir
  })
})

const columns = [
  { accessorKey: 'name', header: '名称' },
  { accessorKey: 'quantity', header: '数量' },
  { accessorKey: 'avg_cost', header: '均价' },
  { accessorKey: 'current_price', header: '现价' },
  { accessorKey: 'market_value', header: '市值' },
  { accessorKey: 'profit', header: '收益' },
  { accessorKey: 'profit_pct', header: '收益率' },
  { accessorKey: 'account', header: '账户' },
  { accessorKey: 'id', header: '操作', enableSorting: false },
]

const positionTypeColor = (t: string) => {
  if (t === 'stock') return 'error'
  if (t === 'fund') return 'info'
  if (t === 'bond') return 'success'
  if (t === 'wealth_mgmt') return 'primary'
  return 'neutral'
}

const summary = ref({ count: 0, total_value: 0, total_cost: 0, total_profit: 0, total_profit_pct: 0 })

const syncing = ref(false)
const syncResult = ref<any>(null)
const syncDetail = computed(() => {
  if (!syncResult.value) return ''
  const parts: string[] = []
  if (syncResult.value.updated) parts.push(`更新 ${syncResult.value.updated} 个`)
  if (syncResult.value.failed) parts.push(`失败 ${syncResult.value.failed} 个`)
  return parts.join('，')
})

const showAddForm = ref(false)
const editingId = ref<number | null>(null)
const submitting = ref(false)
const pendingDelete = ref<Position | null>(null)

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

async function loadData() {
  loading.value = true
  loadError.value = ''
  try {
    // 经统一 api 出口：自动带鉴权 Cookie + 401 跳登录
    const data = await fetchPositionsData()
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
    const data = await syncPositionsApi()
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
}

async function handleSubmit() {
  submitting.value = true
  actionError.value = ''
  try {
    const body = { ...form.value }
    if (editingId.value) {
      await updatePositionApi(editingId.value, body)
    } else {
      await createPositionApi(body)
    }
    showAddForm.value = false
    resetForm()
    await loadData()
  } catch (e: any) {
    actionError.value = e.message || '操作失败'
  } finally {
    submitting.value = false
  }
}

async function confirmDeletePosition() {
  if (!pendingDelete.value) return
  try {
    await deletePositionApi(pendingDelete.value.id)
    pendingDelete.value = null
    await loadData()
  } catch (e: any) {
    pendingDelete.value = null
    actionError.value = e.message || '删除失败'
  }
}

onMounted(loadData)
</script>

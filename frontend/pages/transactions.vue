<template>
  <div class="mx-auto w-full min-w-0 max-w-5xl space-y-6 px-4 py-6 sm:px-6">
    <!-- 页头 -->
    <div class="flex min-w-0 flex-wrap items-center justify-between gap-3">
      <h1 class="sb-h text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">交易记录</h1>
      <div class="flex flex-wrap gap-2">
        <UButton color="primary" @click="showAddModal = true">+ 手动记账</UButton>
        <UButton variant="outline" color="neutral" @click="refresh">刷新</UButton>
      </div>
    </div>

    <!-- 汇总统计（逻辑沿用原 summaryIncome / summaryExpense） -->
    <div
      v-if="!loading && transactions.length > 0"
      class="flex min-w-0 flex-wrap gap-x-8 gap-y-2 px-1 py-1"
    >
      <div class="flex items-center gap-2">
        <span class="text-sm" :style="{ color: 'var(--text-secondary)' }">共</span>
        <span class="text-base font-semibold tabular-nums" :style="{ color: 'var(--text-primary)' }">{{ transactions.length }} 笔</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm" :style="{ color: 'var(--text-secondary)' }">收入</span>
        <span class="text-base font-semibold tabular-nums" :style="{ color: 'var(--success)' }">+¥{{ summaryIncome.toFixed(2) }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm" :style="{ color: 'var(--text-secondary)' }">支出</span>
        <span class="text-base font-semibold tabular-nums" :style="{ color: 'var(--danger)' }">-¥{{ summaryExpense.toFixed(2) }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-sm" :style="{ color: 'var(--text-secondary)' }">净额</span>
        <span
          class="text-base font-semibold tabular-nums"
          :style="{ color: summaryIncome - summaryExpense >= 0 ? 'var(--success)' : 'var(--danger)' }"
        >¥{{ (summaryIncome - summaryExpense).toFixed(2) }}</span>
      </div>
    </div>

    <!-- 筛选（桌面端横排） -->
    <div class="flex min-w-0 flex-wrap items-center gap-2 max-[480px]:hidden">
      <UInput
        v-model="filterSearch"
        type="text"
        placeholder="搜索备注 / 分类 / 账户"
        aria-label="搜索交易"
        class="w-full min-w-0 sm:w-56"
        @update:model-value="onClientFilterChange"
      >
        <template #leading>
          <AppIcon icon="MagnifyingGlass" :size="16" />
        </template>
      </UInput>
      <USelectMenu
        v-model="filterAccount"
        :items="filterAccountItems"
        value-key="value"
        placeholder="全部账户"
        aria-label="按账户筛选"
        class="w-32"
        @update:model-value="onServerFilterChange"
      />
      <USelectMenu
        v-model="filterCategory"
        :items="categoryFilterItems"
        value-key="value"
        placeholder="全部分类"
        aria-label="按分类筛选"
        class="w-32"
        @update:model-value="onServerFilterChange"
      />
      <USelectMenu
        v-model="filterType"
        :items="filterTypeItems"
        value-key="value"
        placeholder="全部类型"
        aria-label="按类型筛选"
        class="w-28"
        @update:model-value="onServerFilterChange"
      />
      <USelectMenu
        v-model="filterDateRange"
        :items="filterDateItems"
        value-key="value"
        placeholder="全部时间"
        aria-label="按时间筛选"
        class="w-32"
        @update:model-value="onClientFilterChange"
      />
      <label
        class="inline-flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm"
        :style="{ background: hideNoise ? 'var(--accent-soft)' : 'var(--bg-secondary)', color: 'var(--text-primary)' }"
      >
        <USwitch v-model="hideNoise" aria-label="仅显示真实交易" @update:model-value="onServerFilterChange" />
        <span>仅显示真实交易</span>
      </label>
      <UButton v-if="hasActiveFilters" variant="ghost" color="neutral" size="sm" @click="clearFilters">清除筛选</UButton>
    </div>

    <!-- 筛选（480px 折叠：原生 details，无手势库依赖） -->
    <details class="tx-filters-disclosure min-[481px]:hidden">
      <summary
        class="flex cursor-pointer items-center justify-between px-1 py-2 text-sm font-medium"
        :style="{ color: 'var(--text-primary)' }"
      >
        <span>筛选{{ activeFilterCount > 0 ? `（${activeFilterCount} 项生效中）` : '' }}</span>
        <span aria-hidden="true">▾</span>
      </summary>
      <div class="mt-2 flex min-w-0 flex-col gap-2">
        <UInput
          v-model="filterSearch"
          type="text"
          placeholder="搜索备注 / 分类 / 账户"
          aria-label="搜索交易"
          class="w-full min-w-0"
          @update:model-value="onClientFilterChange"
        >
          <template #leading>
            <AppIcon icon="MagnifyingGlass" :size="16" />
          </template>
        </UInput>
        <USelectMenu
          v-model="filterAccount"
          :items="filterAccountItems"
          value-key="value"
          placeholder="全部账户"
          aria-label="按账户筛选"
          class="w-full"
          @update:model-value="onServerFilterChange"
        />
        <USelectMenu
          v-model="filterCategory"
          :items="categoryFilterItems"
          value-key="value"
          placeholder="全部分类"
          aria-label="按分类筛选"
          class="w-full"
          @update:model-value="onServerFilterChange"
        />
        <USelectMenu
          v-model="filterType"
          :items="filterTypeItems"
          value-key="value"
          placeholder="全部类型"
          aria-label="按类型筛选"
          class="w-full"
          @update:model-value="onServerFilterChange"
        />
        <USelectMenu
          v-model="filterDateRange"
          :items="filterDateItems"
          value-key="value"
          placeholder="全部时间"
          aria-label="按时间筛选"
          class="w-full"
          @update:model-value="onClientFilterChange"
        />
        <label
        class="inline-flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm"
        :style="{ background: hideNoise ? 'var(--accent-soft)' : 'var(--bg-secondary)', color: 'var(--text-primary)' }"
        >
          <USwitch v-model="hideNoise" aria-label="仅显示真实交易" @update:model-value="onServerFilterChange" />
          <span>仅显示真实交易</span>
        </label>
      <UButton v-if="hasActiveFilters" variant="ghost" color="neutral" size="sm" class="h-9 px-3" @click="clearFilters">清除筛选</UButton>
      </div>
    </details>

    <!-- 批量栏（全选 + 批量删除确认，至少保留批量意识） -->
    <div
      v-if="!loading && searchedTransactions.length > 0"
      class="flex min-w-0 flex-wrap items-center gap-3 rounded-lg px-3 py-2 text-sm"
      :style="{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }"
    >
      <UCheckbox
        :model-value="allFilteredSelected"
        :indeterminate="someSelected"
        aria-label="全选当前筛选结果"
        @update:model-value="toggleSelectAll"
      />
      <span :style="{ color: 'var(--text-secondary)' }">
        {{ selectedIds.length > 0 ? `已选 ${selectedIds.length} 笔` : `全选（共 ${searchedTransactions.length} 笔）` }}
      </span>
      <span class="flex-1" />
      <UButton
        v-if="selectedIds.length > 0"
        color="error"
        variant="outline"
        size="sm"
        @click="batchDeleteVisible = true"
      >
        批量删除（{{ selectedIds.length }}）
      </UButton>
      <UButton v-if="selectedIds.length > 0" variant="ghost" color="neutral" size="sm" @click="selectedIds = []">取消选择</UButton>
    </div>

    <!-- Loading：USkeleton，行布局与原 skeleton-list 对齐 -->
    <div v-if="loading" class="flex flex-col gap-2">
      <div
        v-for="i in 6"
        :key="i"
        class="flex items-center gap-3 rounded-lg p-3"
        :style="{ background: 'var(--bg-secondary)' }"
      >
        <USkeleton class="size-10 shrink-0 rounded-lg" />
        <div class="flex min-w-0 flex-1 flex-col gap-2">
          <USkeleton class="h-4 w-3/5" />
          <USkeleton class="h-3 w-2/5" />
        </div>
        <USkeleton class="h-5 w-20 shrink-0" />
      </div>
    </div>

    <!-- 空态：UEmpty，保留原“暂无交易记录”文案与记一笔入口 -->
    <div
      v-else-if="searchedTransactions.length === 0"
      class="px-4 py-12 text-center"
    >
      <div class="mb-2 flex justify-center" :style="{ color: 'var(--text-tertiary)' }">
        <AppIcon icon="Package" :size="36" />
      </div>
      <div class="mb-1 text-lg font-semibold" :style="{ color: 'var(--text-primary)' }">暂无交易记录</div>
      <p class="mb-1 text-sm" :style="{ color: 'var(--text-secondary)' }">换个筛选条件试试，或记上一笔</p>
      <div class="mt-3 flex justify-center">
        <UButton color="primary" @click="showAddModal = true">记一笔</UButton>
      </div>
    </div>

    <!-- 列表：TransitionGroup 进出保留；行点选展开 inline 编辑 -->
    <TransitionGroup v-else name="tx-list" tag="div" class="sb-rows tx-list flex flex-col">
      <div
        v-for="tx in pagedTransactions"
        :key="tx.id"
        class="tx-item"
        :class="{ editing: editingId === tx.id }"
        @click="startEdit(tx)"
      >
        <div class="flex items-center gap-3 p-3">
          <UCheckbox
            :model-value="isSelected(tx.id)"
            :aria-label="'选择交易' + tx.id"
            @click.stop
            @update:model-value="() => toggleSelect(tx.id)"
          />
          <div class="tx-icon avatar-chip flex size-10 shrink-0 items-center justify-center rounded-lg" :style="{ background: getCategoryIcon(tx.category).color + '20' }">
            <CatGlyph :category="tx.category" :size="20" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate font-medium" :style="{ color: 'var(--text-primary)' }">{{ tx.description || tx.category }}</div>
            <div class="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs" :style="{ color: 'var(--text-secondary)' }">
              <span>{{ getAccountName(tx.account) }}</span>
              <span>{{ tx.category }}</span>
              <span>{{ formatTime(tx.parsed_at) }}</span>
            </div>
          </div>
          <div
            class="tx-amount shrink-0 text-lg font-semibold tabular-nums"
            :style="{ color: tx.transaction_type === 'income' ? 'var(--success)' : 'var(--danger)' }"
          >
            {{ tx.transaction_type === 'income' ? '+' : '-' }}¥{{ tx.amount.toFixed(2) }}
          </div>
          <!-- swipe 留空位：触屏无 hover 时删除按钮常显（纯 CSS，不做手势库） -->
          <UButton
            variant="ghost"
            color="error"
            size="sm"
            square
            class="tx-delete shrink-0"
            title="删除"
            :aria-label="'删除交易' + tx.id"
            @click.stop="handleDelete(tx.id)"
          >×</UButton>
        </div>

        <!-- inline 编辑：金额 / 分类 / 备注回车即存，Esc 取消 -->
        <div
          v-if="editingId === tx.id"
          class="tx-editor border-t px-4 py-3"
          :style="{ borderColor: 'var(--border)' }"
          @click.stop
        >
          <div class="grid min-w-0 grid-cols-1 gap-2 min-[480px]:grid-cols-3">
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" :for="'edit-amount-' + tx.id">金额</label>
              <UInput
                :id="'edit-amount-' + tx.id"
                v-model.number="editForm.amount"
                type="number"
                step="0.01"
                min="0.01"
                required
                class="w-full min-w-0 tabular-nums"
                @keydown.enter="submitEdit"
                @keydown.esc="cancelEdit"
              />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">分类</label>
              <USelectMenu
                v-model="editForm.category"
                :items="categoryOptions"
                placeholder="选择或输入新分类"
                search-input
                create-item="always"
                class="w-full"
                @create="onCreateEditCategory"
                @update:model-value="onCategoryCreate"
              />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" :for="'edit-desc-' + tx.id">备注</label>
              <UInput
                :id="'edit-desc-' + tx.id"
                v-model="editForm.description"
                type="text"
                placeholder="备注"
                class="w-full min-w-0"
                @keydown.enter="submitEdit"
                @keydown.esc="cancelEdit"
              />
            </div>
          </div>
          <div class="mt-2 grid min-w-0 grid-cols-1 gap-2 min-[480px]:grid-cols-2">
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">类型</label>
              <USelectMenu v-model="editForm.transaction_type" :items="txTypeItems" value-key="value" class="w-full" />
            </div>
            <div class="min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">账户</label>
              <USelectMenu v-model="editForm.account" :items="formAccountItems" value-key="value" class="w-full" />
            </div>
          </div>
          <p class="mt-2 text-xs" :style="{ color: 'var(--text-tertiary)' }">回车保存 · Esc 取消</p>
          <div class="mt-3 flex justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="cancelEdit">取消</UButton>
            <UButton color="primary" :loading="submitting" :disabled="submitting" @click="submitEdit">
              {{ submitting ? '保存中...' : '保存修改' }}
            </UButton>
          </div>
        </div>
      </div>
    </TransitionGroup>

    <!-- 加载更多（分页替代：本地切片，接口仍一次拉 limit=500） -->
    <div v-if="!loading && searchedTransactions.length > 0" class="mt-3 flex flex-col items-center gap-2">
      <UButton
        v-if="hasMore"
        variant="outline"
        color="neutral"
        @click="loadMore"
      >
        加载更多（已显示 {{ pagedTransactions.length }} / 共 {{ searchedTransactions.length }} 笔）
      </UButton>
      <p v-else-if="searchedTransactions.length > PAGE_SIZE" class="text-xs" :style="{ color: 'var(--text-tertiary)' }">
        已显示全部 {{ searchedTransactions.length }} 笔
      </p>
    </div>

    <!-- 新增弹窗：UModal -->
    <UModal v-model:open="showAddModal" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-lg' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="mb-4 text-base font-semibold" :style="{ color: 'var(--text-primary)' }">新增交易</h3>
          <form @submit.prevent="submitTransaction">
            <div class="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2">
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">类型</label>
                <USelectMenu v-model="form.transaction_type" :items="txTypeItems" value-key="value" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="add-amount">金额</label>
                <UInput
                  id="add-amount"
                  v-model.number="form.amount"
                  type="number"
                  step="0.01"
                  min="0.01"
                  required
                  placeholder="0.00"
                  class="w-full min-w-0 tabular-nums"
                />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">账户</label>
                <USelectMenu v-model="form.account" :items="formAccountItems" value-key="value" class="w-full" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }">分类</label>
                <USelectMenu
                  v-model="form.category"
                  :items="categoryOptions"
                  placeholder="选择或输入新分类"
                  search-input
                  create-item="always"
                  class="w-full"
                  @create="onCreateAddCategory"
                  @update:model-value="onCategoryCreate"
                />
              </div>
            </div>
            <div class="mt-3 min-w-0">
              <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="add-desc">描述</label>
              <UInput
                id="add-desc"
                v-model="form.description"
                type="text"
                placeholder="备注（可选）"
                class="w-full min-w-0"
              />
            </div>
            <div class="mt-4 flex justify-end gap-2">
              <UButton variant="outline" color="neutral" @click="showAddModal = false">取消</UButton>
              <UButton type="submit" color="primary" :loading="submitting" :disabled="submitting">
                {{ submitting ? '保存中...' : '保存' }}
              </UButton>
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- 删除确认：UModal + 明确后果文案 -->
    <UModal v-model:open="deleteDialogVisible" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">删除交易</h3>
          <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">
            确定要删除这条交易记录吗？删除后无法恢复，此操作不可撤销。
          </p>
          <div class="flex justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="deleteDialogVisible = false">取消</UButton>
            <UButton color="error" :loading="deleting" :disabled="deleting" @click="confirmDelete">删除</UButton>
          </div>
        </UCard>
      </template>
    </UModal>

    <!-- 批量删除确认：UModal + 明确后果文案（含笔数） -->
    <UModal v-model:open="batchDeleteVisible" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">批量删除交易</h3>
          <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">
            将永久删除选中的 {{ selectedIds.length }} 笔交易记录，删除后无法恢复，此操作不可撤销。
          </p>
          <div class="flex justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="batchDeleteVisible = false">取消</UButton>
            <UButton color="error" :loading="batchDeleting" :disabled="batchDeleting" @click="confirmBatchDelete">
              {{ batchDeleting ? '删除中...' : `确认删除 ${selectedIds.length} 笔` }}
            </UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onActivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchTransactions, createTransaction, updateTransaction, deleteTransaction } from '~/utils/api'
import { getCategoryIcon, getAllKnownCategories, assignAutoStyle } from '~/utils/icons'

const toast = useToast()
const route = useRoute()
const router = useRouter()

const PAGE_SIZE = 50

const transactions = ref([])
const loading = ref(true)
const filterAccount = ref('')
const filterCategory = ref('')
const filterType = ref('')
const filterDateRange = ref('')
const filterSearch = ref('')
const hideNoise = ref(true) // 默认隐藏0元垃圾通知
const visibleCount = ref(PAGE_SIZE)

// 汇总（逻辑与原版一致：基于已加载集合统计）
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
// USelectMenu 新建菜单用：字符串 items（用法同 pages/add.vue）
const categoryOptions = computed(() => allCategories.value)
const onCategoryCreate = (val) => {
  const name = (val || '').trim()
  if (!name) return
  assignAutoStyle(name)
  customTick.value++
}

// 类型 / 账户 / 时间选项（value 保持原接口字段语义：code  그대로）
const txTypeItems = [
  { label: '支出', value: 'expense' },
  { label: '收入', value: 'income' }
]
const filterTypeItems = [
  { label: '全部类型', value: '' },
  { label: '支出', value: 'expense' },
  { label: '收入', value: 'income' }
]
// 新增/编辑账户：与原版写死 7 项一致
const formAccountItems = [
  { label: '招商银行', value: 'cmb' },
  { label: '工商银行', value: 'icbc' },
  { label: '建设银行', value: 'ccb' },
  { label: '支付宝', value: 'alipay' },
  { label: '微信支付', value: 'wechat_pay' },
  { label: '现金', value: 'cash' },
  { label: '其他', value: 'other' }
]
// 筛选账户：与原版筛选 14 项一致
const filterAccountItems = [
  { label: '全部账户', value: '' },
  { label: '招商银行', value: 'cmb' },
  { label: '工商银行', value: 'icbc' },
  { label: '建设银行', value: 'ccb' },
  { label: '农业银行', value: 'abc' },
  { label: '中国银行', value: 'boc' },
  { label: '交通银行', value: 'bocom' },
  { label: '浦发银行', value: 'spdb' },
  { label: '支付宝', value: 'alipay' },
  { label: '微信支付', value: 'wechat_pay' },
  { label: '美团', value: 'meituan' },
  { label: '京东', value: 'jd' },
  { label: '现金', value: 'cash' }
]
const filterDateItems = [
  { label: '全部时间', value: '' },
  { label: '今天', value: 'today' },
  { label: '最近7天', value: 'week' },
  { label: '最近30天', value: 'month' }
]
const categoryFilterItems = computed(() => [
  { label: '全部分类', value: '' },
  ...allCategories.value.map(c => ({ label: c, value: c }))
])

// 筛选状态 → URL query 同步（?category=&type=&account=&q=&range=，首页分类榜穿透与刷新保持依赖它）
const buildQuery = () => {
  const q = {}
  if (filterCategory.value) q.category = filterCategory.value
  if (filterType.value) q.type = filterType.value
  if (filterAccount.value) q.account = filterAccount.value
  if (filterSearch.value.trim()) q.q = filterSearch.value.trim()
  if (filterDateRange.value) q.range = filterDateRange.value
  return q
}
const syncQuery = () => {
  const q = buildQuery()
  const cur = route.query
  const keys = Object.keys(q)
  const curKeys = Object.keys(cur).filter(k => ['category', 'type', 'account', 'q', 'range'].includes(k))
  const same = keys.length === curKeys.length && keys.every(k => cur[k] === q[k])
  if (!same) router.replace({ query: q })
}
// ?category=xxx 入参预筛（首页分类榜穿透依赖）
const applyQueryToFilters = () => {
  const q = route.query
  if (typeof q.category === 'string') filterCategory.value = q.category
  if (typeof q.type === 'string') filterType.value = q.type
  if (typeof q.account === 'string') filterAccount.value = q.account
  if (typeof q.q === 'string') filterSearch.value = q.q
  if (typeof q.range === 'string' && ['', 'today', 'week', 'month'].includes(q.range)) filterDateRange.value = q.range
}

const hasActiveFilters = computed(() =>
  !!(filterAccount.value || filterCategory.value || filterType.value || filterDateRange.value || filterSearch.value.trim() || !hideNoise.value)
)
const activeFilterCount = computed(() =>
  [filterAccount.value, filterCategory.value, filterType.value, filterDateRange.value, filterSearch.value.trim()].filter(Boolean).length
    + (hideNoise.value ? 0 : 1)
)
const clearFilters = () => {
  filterAccount.value = ''
  filterCategory.value = ''
  filterType.value = ''
  filterDateRange.value = ''
  filterSearch.value = ''
  hideNoise.value = true
  syncQuery()
  loadTransactions()
}

// 服务端筛选变化：同步 query + 重载（原 @change="loadTransactions" 等价）
const onServerFilterChange = () => {
  syncQuery()
  resetSelection()
  loadTransactions()
}
// 客户端筛选（搜索/时间）变化：同步 query + 重置可见数，不打接口
const onClientFilterChange = () => {
  syncQuery()
  visibleCount.value = PAGE_SIZE
}

// 手动记账（新增走 UModal，表单字段与原内联表单逻辑不变）
const showAddModal = ref(false)
const submitting = ref(false)
const form = ref({
  amount: null,
  category: '餐饮',
  account: 'wechat_pay',
  description: '',
  transaction_type: 'expense'
})
// USelectMenu 新建词入口：等价原 allow-create 行为，照旧调 assignAutoStyle 落盘
const onCreateAddCategory = (term) => {
  const name = (term || '').trim()
  if (!name) return
  form.value.category = name
  onCategoryCreate(name)
}

// inline 编辑（行点选展开；金额/分类/备注回车即存，Esc 取消）
const editingId = ref(null)
const clientReady = ref(false)
const editForm = ref({ amount: 0, category: '', account: '', description: '', transaction_type: 'expense' })
const onCreateEditCategory = (term) => {
  const name = (term || '').trim()
  if (!name) return
  editForm.value.category = name
  onCategoryCreate(name)
}

// 搜索（客户端过滤：备注/分类/账户名/金额；服务端参数一字不改）
const searchedTransactions = computed(() => {
  const q = filterSearch.value.trim().toLowerCase()
  if (!q) return transactions.value
  return transactions.value.filter(t =>
    ((t.description || '') + ' ' + (t.category || '') + ' ' + getAccountName(t.account) + ' ' + String(t.amount))
      .toLowerCase().includes(q)
  )
})

// 加载更多（本地切片；接口仍一次拉 limit=500，一字不改）
const pagedTransactions = computed(() => searchedTransactions.value.slice(0, visibleCount.value))
const hasMore = computed(() => visibleCount.value < searchedTransactions.value.length)
const loadMore = () => { visibleCount.value += PAGE_SIZE }

// 批量选择（至少全选删除确认）
const selectedIds = ref([])
const isSelected = id => selectedIds.value.includes(id)
const allFilteredSelected = computed(() =>
  searchedTransactions.value.length > 0 && selectedIds.value.length === searchedTransactions.value.length
)
const someSelected = computed(() =>
  selectedIds.value.length > 0 && selectedIds.value.length < searchedTransactions.value.length
)
const toggleSelect = (id) => {
  const i = selectedIds.value.indexOf(id)
  if (i >= 0) selectedIds.value.splice(i, 1)
  else selectedIds.value.push(id)
}
const toggleSelectAll = () => {
  if (allFilteredSelected.value) selectedIds.value = []
  else selectedIds.value = searchedTransactions.value.map(t => t.id)
}
const resetSelection = () => { selectedIds.value = [] }

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
    visibleCount.value = PAGE_SIZE
    // 已删除/已过滤掉的行自动脱选
    const alive = new Set(transactions.value.map(t => t.id))
    selectedIds.value = selectedIds.value.filter(id => alive.has(id))
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
    onCategoryCreate(form.value.category) // 直接提交的新词同样落盘
    const created = await createTransaction({
      amount: form.value.amount,
      category: form.value.category,
      account: form.value.account,
      description: form.value.description || undefined,
      transaction_type: form.value.transaction_type,
      confidence: 1.0
    })
    form.value.amount = null
    form.value.description = ''
    showAddModal.value = false
    await loadTransactions()
    toast.add({ title: created?.balance_updated === false ? '记账成功（账户名对不上余额表，未联动余额）' : '记账成功', color: 'success' })
  } catch (error) {
    console.error('创建交易失败:', error)
    toast.add({ title: '保存失败，请重试', color: 'error' })
  } finally {
    submitting.value = false
  }
}

const startEdit = (tx) => {
  if (editingId.value === tx.id) return
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
    onCategoryCreate(editForm.value.category) // inline 新建分类同样落盘
    await updateTransaction(editingId.value, {
      amount: editForm.value.amount,
      category: editForm.value.category,
      account: editForm.value.account,
      description: editForm.value.description || undefined,
      transaction_type: editForm.value.transaction_type
    })
    editingId.value = null
    await loadTransactions()
    toast.add({ title: '已保存修改', color: 'success' })
  } catch (error) {
    console.error('更新失败:', error)
    toast.add({ title: '更新失败，请重试', color: 'error' })
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

// 删除确认（UModal + 明确后果文案）
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
    toast.add({ title: '已删除该笔交易', color: 'neutral' })
  } catch (error) {
    console.error('删除失败:', error)
    toast.add({ title: '删除失败，请重试', color: 'error' })
  } finally {
    deleting.value = false
  }
}

// 批量删除确认（逐笔调既有删除接口，不新增接口）
const batchDeleteVisible = ref(false)
const batchDeleting = ref(false)

const confirmBatchDelete = async () => {
  if (selectedIds.value.length === 0) return
  batchDeleting.value = true
  try {
    const ids = [...selectedIds.value]
    for (const id of ids) {
      await deleteTransaction(id)
    }
    batchDeleteVisible.value = false
    selectedIds.value = []
    await loadTransactions()
    toast.add({ title: `已删除 ${ids.length} 笔交易`, color: 'neutral' })
  } catch (error) {
    console.error('批量删除失败:', error)
    toast.add({ title: '批量删除失败，请重试', color: 'error' })
  } finally {
    batchDeleting.value = false
  }
}

const init = () => { setTimeout(() => { clientReady.value = true }, 0); applyQueryToFilters(); loadTransactions() }
onMounted(init)
onActivated(init) // 客户端路由导航回来时也重新加载（含首页穿透 query）
</script>

<style scoped>
/* 列表进出动效（原 tx-list 保留） */
.tx-list-enter-active,
.tx-list-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.tx-list-enter-from,
.tx-list-leave-to {
  opacity: 0;
  transform: translateY(6px);
}
.tx-list-move {
  transition: transform 0.25s ease;
}

.tx-item {
  border-radius: var(--radius-md);
  transition: background 0.2s ease;
  cursor: pointer;
}
.tx-item:hover {
  background: var(--bg-tertiary, rgba(255, 255, 255, 0.03));
}
.tx-item.editing {
  background: var(--accent-soft);
}

/* 触屏无 hover：删除按钮常显（swipe 留空位，不做手势库） */
.tx-item .tx-delete {
  opacity: 0;
  transition: opacity 0.2s ease;
}
.tx-item:hover .tx-delete,
.tx-item.editing .tx-delete {
  opacity: 1;
}
@media (hover: none) {
  .tx-item .tx-delete {
    opacity: 1;
  }
}

/* 480px：筛选折叠 details 样式 */
.tx-filters-disclosure summary {
  list-style: none;
}
.tx-filters-disclosure summary::-webkit-details-marker {
  display: none;
}
.tx-filters-disclosure summary span:last-child {
  transition: transform 0.2s ease;
}
.tx-filters-disclosure[open] summary span:last-child {
  transform: rotate(180deg);
}

@media (prefers-reduced-motion: reduce) {
  .tx-list-enter-active,
  .tx-list-leave-active,
  .tx-list-move,
  .tx-item,
  .tx-item .tx-delete,
  .tx-filters-disclosure summary span:last-child {
    transition: none;
  }
}
</style>

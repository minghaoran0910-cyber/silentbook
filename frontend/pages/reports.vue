<template>
  <div class="mx-auto min-w-0 w-full max-w-4xl px-4 py-6">
    <div class="mb-4 flex flex-wrap items-center gap-3">
      <div class="mr-auto min-w-0">
        <h1 class="sb-h text-xl font-semibold" style="color: var(--text-primary)">财务报表</h1>
        <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">按天、按周、按月、按年，看钱的进出。</p>
      </div>
    </div>

    <UTabs v-model="activeTab" :items="tabItems" :content="false" class="mb-4" />

    <!-- 复盘结论：先看省没省，再看趋势明细 -->
    <UCard
      v-if="!loading && !error && reviewLine"
      class="mb-4"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-4' }"
    >
      <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
        <p class="min-w-0 flex-1 text-sm leading-6" style="color: var(--text-primary)">{{ reviewLine }}</p>
        <UBadge v-if="reviewRate !== null" color="neutral" variant="soft" class="shrink-0 tabular-nums">储蓄率 {{ reviewRate }}%</UBadge>
      </div>
    </UCard>

    <!-- 加载中：骨架 -->
    <div v-if="loading" class="space-y-4">
      <UCard :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }" :ui="{ body: 'p-5' }">
        <USkeleton class="h-6 w-40" />
        <div class="mt-4 grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
          <USkeleton v-for="i in 4" :key="i" class="h-[76px] w-full" />
        </div>
        <USkeleton class="mt-4 h-4 w-full" />
        <USkeleton class="mt-2 h-4 w-5/6" />
      </UCard>
    </div>

    <UAlert
      v-else-if="error"
      color="error"
      variant="soft"
      :title="error"
    >
      <template #description>
        <p>网络可能开小差了，稍后再试一次。</p>
        <UButton size="sm" class="mt-2" @click="fetchReport(activeTab)">重新加载</UButton>
      </template>
    </UAlert>

    <!-- 日报 -->
    <UCard
      v-else-if="activeTab === 'daily'"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="sb-h mb-4 text-base font-semibold tabular-nums" style="color: var(--text-primary)">{{ dailyReport.date }} 日报</h2>
      <div class="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总收入</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--success)">¥{{ dailyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--danger)">¥{{ dailyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">净收入</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" :style="{ color: dailyReport.net >= 0 ? 'var(--success)' : 'var(--danger)' }">
            ¥{{ dailyReport.net?.toFixed(2) || '0.00' }}
          </div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">交易笔数</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">{{ dailyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="dailyReport.categories?.length" class="mt-5">
        <h3 class="sb-h mb-2 text-sm font-semibold" style="color: var(--text-primary)">支出分类</h3>
        <ul class="divide-y" style="border-color: var(--border)">
          <li v-for="cat in dailyReport.categories" :key="cat.name" class="flex items-center gap-3 py-2">
            <span class="min-w-[80px] text-sm" style="color: var(--text-primary)">{{ cat.name }}</span>
            <span class="ml-auto text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ cat.amount.toFixed(2) }}</span>
          </li>
        </ul>
      </div>
      <div v-else-if="isEmpty(dailyReport)" class="py-8 text-center">
        <AppIcon icon="Receipt" :size="28" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="mt-2 text-sm" style="color: var(--text-secondary)">这一天还没有记账。</p>
        <UButton to="/add" size="sm" class="mt-3">去记一笔</UButton>
      </div>
    </UCard>

    <!-- 周报 -->
    <UCard
      v-else-if="activeTab === 'weekly'"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="sb-h mb-4 text-base font-semibold tabular-nums" style="color: var(--text-primary)">{{ weeklyReport.week_start }} ~ {{ weeklyReport.week_end }} 周报</h2>
      <div class="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总收入</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--success)">¥{{ weeklyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--danger)">¥{{ weeklyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">日均支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ weeklyReport.daily_avg_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">交易笔数</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">{{ weeklyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="weeklyReport.daily?.length" class="mt-5">
        <h3 class="sb-h mb-2 text-sm font-semibold" style="color: var(--text-primary)">每日明细</h3>
        <ul class="space-y-2">
          <li v-for="day in weeklyReport.daily" :key="day.date" class="flex items-center gap-3">
            <span class="w-32 shrink-0 truncate text-xs tabular-nums" style="color: var(--text-primary)">{{ day.weekday }} ({{ day.date }})</span>
            <div class="min-w-0 flex-1 space-y-1" aria-hidden="true">
              <div class="h-1 overflow-hidden rounded-full" style="background: var(--border)">
                <div class="h-full rounded-full transition-[width] motion-reduce:transition-none" :style="{ background: 'var(--success)', width: weekBarW(day.income) + '%' }" />
              </div>
              <div class="h-1 overflow-hidden rounded-full" style="background: var(--border)">
                <div class="h-full rounded-full transition-[width] motion-reduce:transition-none" :style="{ background: 'var(--danger)', width: weekBarW(day.expense) + '%' }" />
              </div>
            </div>
            <span class="w-36 shrink-0 text-right text-xs tabular-nums" style="color: var(--text-secondary)">
              <span v-if="day.income > 0" style="color: var(--success)">+¥{{ day.income.toFixed(2) }}</span>
              <span v-if="day.income > 0 && day.expense > 0"> / </span>
              <span v-if="day.expense > 0" style="color: var(--danger)">-¥{{ day.expense.toFixed(2) }}</span>
              <span v-if="!(day.income > 0) && !(day.expense > 0)">—</span>
              <span class="ml-1">{{ day.count }}笔</span>
            </span>
          </li>
        </ul>
      </div>
      <div v-else-if="isEmpty(weeklyReport)" class="py-8 text-center">
        <AppIcon icon="Receipt" :size="28" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="mt-2 text-sm" style="color: var(--text-secondary)">这一周还没有记账。</p>
        <UButton to="/add" size="sm" class="mt-3">去记一笔</UButton>
      </div>
    </UCard>

    <!-- 月报 -->
    <UCard
      v-else-if="activeTab === 'monthly'"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="sb-h mb-4 text-base font-semibold tabular-nums" style="color: var(--text-primary)">{{ monthlyReport.year }}年{{ monthlyReport.month }}月 月报</h2>
      <div class="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总收入</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--success)">¥{{ monthlyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--danger)">¥{{ monthlyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">储蓄率</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">{{ monthlyReport.savings_rate?.toFixed(1) || '0.0' }}%</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">交易笔数</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">{{ monthlyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="monthlyReport.expense_categories?.length" class="mt-5">
        <div class="mb-2 flex items-center gap-2">
          <h3 class="sb-h text-sm font-semibold" style="color: var(--text-primary)">支出分类</h3>
          <UButton
            v-if="monthlyReport.expense_categories.length > 5"
            variant="ghost"
            size="xs"
            class="ml-auto"
            @click="monthExpanded = !monthExpanded"
          >{{ monthExpanded ? '收起' : `展开全部（${monthlyReport.expense_categories.length}类）` }}</UButton>
        </div>
        <ul class="space-y-2.5">
          <li v-for="cat in visibleMonthlyCats" :key="cat.name" class="flex items-center gap-3">
            <span class="w-16 shrink-0 truncate text-sm" style="color: var(--text-primary)">{{ cat.name }}</span>
            <UProgress :model-value="pctOf(cat.amount, monthlyReport.total_expense)" :max="100" size="sm" class="min-w-0 flex-1 motion-reduce:transition-none" />
            <span class="w-20 shrink-0 text-right text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ cat.amount.toFixed(2) }}</span>
            <span class="w-12 shrink-0 text-right text-xs tabular-nums" style="color: var(--text-secondary)">{{ pctOf(cat.amount, monthlyReport.total_expense).toFixed(1) }}%</span>
          </li>
        </ul>
      </div>
      <div v-else-if="isEmpty(monthlyReport)" class="py-8 text-center">
        <AppIcon icon="Receipt" :size="28" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="mt-2 text-sm" style="color: var(--text-secondary)">这个月还没有记账。</p>
        <UButton to="/add" size="sm" class="mt-3">去记一笔</UButton>
      </div>
    </UCard>

    <!-- 年报 -->
    <UCard
      v-else-if="activeTab === 'yearly'"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="sb-h mb-4 text-base font-semibold tabular-nums" style="color: var(--text-primary)">{{ yearlyReport.year }}年 年报</h2>
      <div class="grid grid-cols-2 gap-3 min-[480px]:grid-cols-4">
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总收入</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--success)">¥{{ yearlyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">总支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--danger)">¥{{ yearlyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">储蓄率</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">{{ yearlyReport.savings_rate?.toFixed(1) || '0.0' }}%</div>
        </div>
        <div class="rounded-lg p-3 text-center" style="background: var(--bg-primary)">
          <div class="text-xs" style="color: var(--text-secondary)">月均支出</div>
          <div class="mt-1 text-lg font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ yearlyReport.monthly_avg_expense?.toFixed(2) || '0.00' }}</div>
        </div>
      </div>
      <div v-if="yearlyReport.monthly?.length" class="mt-5">
        <h3 class="sb-h mb-2 text-sm font-semibold" style="color: var(--text-primary)">月度趋势</h3>
        <div ref="yearlyEl" class="h-[260px] w-full" role="img" aria-label="月度收支趋势图"></div>
      </div>
      <div v-else-if="isEmpty(yearlyReport)" class="py-8 text-center">
        <AppIcon icon="Receipt" :size="28" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="mt-2 text-sm" style="color: var(--text-secondary)">这一年还没有记账。</p>
        <UButton to="/add" size="sm" class="mt-3">去记一笔</UButton>
      </div>
    </UCard>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { computed } from 'vue'
import { fetchReport as fetchReportApi } from '~/utils/api'
import { useECharts, axisCommon, tooltipCommon } from '~/composables/useECharts'

// 当前报表页签：记住上次看到哪一份（客户端 localStorage）
const REPORT_TAB_KEY = 'sb-reports-tab'
const readSavedTab = () => {
  if (!import.meta.client) return 'daily'
  try {
    const t = localStorage.getItem(REPORT_TAB_KEY)
    return ['daily', 'weekly', 'monthly', 'yearly'].includes(t) ? t : 'daily'
  } catch { return 'daily' }
}
const activeTab = ref(readSavedTab())
const tabItems = [
  { label: '日报', value: 'daily' },
  { label: '周报', value: 'weekly' },
  { label: '月报', value: 'monthly' },
  { label: '年报', value: 'yearly' },
]
const loading = ref(false)
const error = ref('')

const dailyReport = ref({})
const weeklyReport = ref({})
const monthlyReport = ref({})
const yearlyReport = ref({})

// 复盘派生（新增，不动原字段/公式）：复盘句 + 月分类排序折叠 + 周迷你条比例
const monthExpanded = ref(false)
const sortedMonthlyCats = computed(() => {
  const list = monthlyReport.value.expense_categories || []
  return [...list].sort((a, b) => b.amount - a.amount)
})
const visibleMonthlyCats = computed(() => {
  return monthExpanded.value ? sortedMonthlyCats.value : sortedMonthlyCats.value.slice(0, 5)
})
const weekMaxAmt = computed(() => {
  const days = weeklyReport.value.daily || []
  return Math.max(0, ...days.map((d) => Math.max(d.income || 0, d.expense || 0)))
})
const weekBarW = (v) => {
  const m = weekMaxAmt.value
  if (!m) return 0
  return Math.min(100, ((v || 0) / m) * 100)
}
const reviewSource = computed(() => {
  if (activeTab.value === 'daily') return { label: '本日', r: dailyReport.value, cats: dailyReport.value.categories || [] }
  if (activeTab.value === 'weekly') return { label: '本周', r: weeklyReport.value, cats: [] }
  if (activeTab.value === 'yearly') return { label: '今年', r: yearlyReport.value, cats: [] }
  return { label: '本月', r: monthlyReport.value, cats: monthlyReport.value.expense_categories || [] }
})
const reviewLine = computed(() => {
  const { label, r, cats } = reviewSource.value
  if (!r || Object.keys(r).length === 0 || (r.transaction_count || 0) === 0) return ''
  const income = r.total_income || 0
  const expense = r.total_expense || 0
  const net = r.net ?? (income - expense)
  if (net >= 0) return `${label}盈余 ¥${net.toFixed(2)}，省下来了，继续保持！`
  const top = [...cats].sort((a, b) => b.amount - a.amount)[0]
  if (top) return `${label}赤字 ¥${Math.abs(net).toFixed(2)}，最大支出在「${top.name}」¥${top.amount.toFixed(2)}，先从这笔看看能不能省。`
  return `${label}赤字 ¥${Math.abs(net).toFixed(2)}，支出超过了收入，看看哪笔能省。`
})
const reviewRate = computed(() => {
  const v = reviewSource.value.r?.savings_rate
  return v === null || v === undefined ? null : Number(v).toFixed(1)
})
watch(activeTab, () => { monthExpanded.value = false })

// 分类占比：分母为 0 时按 0 处理，其余与原公式一致
const pctOf = (amount, total) => {
  if (!total) return 0
  return (amount / total) * 100
}
// 空报表：拉回来但一笔交易都没有
const isEmpty = (report) => {
  return report && Object.keys(report).length > 0 && (report.transaction_count || 0) === 0
}

// 年报月度趋势 echarts（图例默认可点：点中显隐对应柱）
const { el: yearlyEl, render: renderYearly } = useECharts()
watch(yearlyReport, (y) => {
  if (!y.monthly?.length) return
  renderYearly((p) => ({
    grid: { left: 8, right: 8, top: 24, bottom: 0, containLabel: true },
    tooltip: { ...tooltipCommon(p), valueFormatter: (v) => `¥${Number(v).toFixed(0)}` },
    legend: {
      top: 0, right: 0, textStyle: { color: p.subtext, fontSize: 11 },
      itemWidth: 12, itemHeight: 8,
    },
    xAxis: {
      type: 'category',
      data: y.monthly.map((m) => `${m.month}月`),
      ...axisCommon(p),
    },
    yAxis: { type: 'value', ...axisCommon(p) },
    series: [
      {
        name: '收入', type: 'bar', data: y.monthly.map((m) => m.income),
        itemStyle: { color: p.success, borderRadius: [3, 3, 0, 0] },
      },
      {
        name: '支出', type: 'bar', data: y.monthly.map((m) => m.expense),
        itemStyle: { color: p.danger, borderRadius: [3, 3, 0, 0] },
      },
    ],
  }))
}, { deep: true })

const fetchReport = async (type) => {
  loading.value = true
  error.value = ''
  try {
    // 经统一 api 出口：自动带鉴权 Cookie + 401 跳登录
    const data = await fetchReportApi(type)

    if (type === 'daily') dailyReport.value = data
    else if (type === 'weekly') weeklyReport.value = data
    else if (type === 'monthly') monthlyReport.value = data
    else if (type === 'yearly') yearlyReport.value = data
  } catch (e) {
    error.value = '加载失败: ' + e.message
  } finally {
    loading.value = false
  }
}

watch(activeTab, (newTab) => {
  try {
    if (import.meta.client) localStorage.setItem(REPORT_TAB_KEY, newTab)
  } catch {}
  fetchReport(newTab)
})

onMounted(() => {
  fetchReport(activeTab.value)
})
</script>

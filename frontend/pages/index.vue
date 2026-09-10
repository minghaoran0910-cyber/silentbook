<template>
  <div class="mx-auto w-full max-w-5xl space-y-6 px-4 py-6 sm:px-6">
    <!-- 顶栏：标题 + 币种 + 一键记一笔 -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="mr-auto min-w-0">
        <h1 class="sb-h text-xl" style="color: var(--text-primary)">总览</h1>
        <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">钱在哪里，今天发生了什么，下一步做什么。</p>
      </div>
      <USelect
        v-model="displayCurrency"
        :items="currencyItems"
        aria-label="展示币种"
        class="w-36"
      />
      <UButton to="/add" class="cta-press sb-cta">
        <AppIcon icon="Plus" :size="16" />
        记一笔
      </UButton>
    </div>
    <p class="text-xs" style="color: var(--text-tertiary)">
      以人民币记账{{ displayCurrency === 'CNY' ? '' : ` · 按${fxDate || '实时'}汇率折算为 ${displayCurrency} 展示` }}
    </p>

    <!-- 一、 increases 有多少钱：净资产置顶 + 面积图 -->
    <section aria-label="有多少钱" class="space-y-4">
      <UCard :class="['sb-surface', playEnter && 'reveal']" :style="{ '--reveal-delay': '0ms' }">
        <div class="flex flex-wrap items-end justify-between gap-3">
          <div>
            <div class="text-sm" style="color: var(--text-secondary)">净资产</div>
            <div class="sb-display mt-1 text-5xl font-semibold tabular-nums" style="color: var(--text-primary)">
              {{ netAssets.display.value }}
            </div>
            <div class="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm tabular-nums">
              <span style="color: var(--text-secondary)">
                总资产 <span class="font-medium" style="color: var(--success)">{{ totalAssets.display.value }}</span>
              </span>
              <span style="color: var(--text-secondary)">
                总负债 <span class="font-medium" style="color: var(--danger)">{{ totalLiabilities.display.value }}</span>
              </span>
            </div>
            <p class="mt-1 text-xs" style="color: var(--text-tertiary)">净资产 = 账户余额 + 资产 − 负债，同一笔钱不要两处都记</p>
          </div>
          <UButton to="/assets" variant="ghost" color="neutral">
            管理资产
          </UButton>
        </div>
        <div
          v-if="mounted && (assets.length > 0 || liabilities.length > 0)"
          class="mt-4 flex h-6 w-full gap-0.5 overflow-hidden"
          style="border-radius: var(--radius-md)"
          role="img"
          aria-label="资产与负债占比"
        >
          <div
            class="flex h-full items-center justify-center overflow-hidden text-xs font-medium whitespace-nowrap"
            style="background: var(--success); color: var(--fill-ink)"
            :style="{ width: (totalAssetValue / Math.max(totalAssetValue + totalLiabilityValue, 1) * 100) + '%' }"
          >
            <span v-if="totalAssetValue > 0 && totalAssetValue / Math.max(totalAssetValue + totalLiabilityValue, 1) > 0.06" class="px-2">资产 ¥{{ totalAssetValue.toFixed(0) }}</span>
          </div>
          <div
            class="flex h-full items-center justify-center overflow-hidden text-xs font-medium whitespace-nowrap"
            style="background: var(--danger); color: var(--fill-ink)"
            :style="{ width: (totalLiabilityValue / Math.max(totalAssetValue + totalLiabilityValue, 1) * 100) + '%' }"
          >
            <span v-if="totalLiabilityValue > 0 && totalLiabilityValue / Math.max(totalAssetValue + totalLiabilityValue, 1) > 0.06" class="px-2">负债 ¥{{ totalLiabilityValue.toFixed(0) }}</span>
          </div>
        </div>
      </UCard>

      <!-- stat 指标：无框，留白即分隔 -->
      <div class="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-3 lg:grid-cols-6">
        <div
          v-for="(s, i) in statCards"
          :key="s.key"
          :class="['sb-metric', playEnter && 'reveal']"
          :style="{ '--reveal-delay': `${i * 40}ms` }"
        >
          <div class="sb-label text-xs" style="color: var(--text-secondary)">{{ s.label }}</div>
          <div class="mt-1 truncate text-xl font-semibold tabular-nums" :style="{ color: s.color }">
            {{ s.text }}
          </div>
        </div>
      </div>

      <!-- 消费趋势面积图 -->
      <UCard class="sb-surface">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="sb-h text-base" style="color: var(--text-primary)">近{{ trendDays }}天资金流动</h2>
          <span class="text-xs tabular-nums" style="color: var(--text-secondary)">
            支出 ¥{{ trend.total_expense.toFixed(2) }} · 收入 ¥{{ trend.total_income.toFixed(2) }}
          </span>
        </div>
        <USkeleton v-if="!trendLoaded" class="h-[260px] w-full" />
        <div v-else-if="trend.daily.length > 0" ref="trendEl" class="sb-plot h-[260px] w-full"></div>
        <p v-else class="py-12 text-center text-sm" style="color: var(--text-secondary)">暂无交易数据，先记第一笔吧。</p>
      </UCard>

      <!-- 资产分类明细：无框列表 -->
      <section v-if="mounted && assetBreakdown.length > 0" aria-label="资产分布">
        <h2 class="sb-h mb-3 text-base" style="color: var(--text-primary)">资产分布</h2>
        <ul class="space-y-2.5">
          <li v-for="item in assetBreakdown" :key="item.type" class="flex items-center gap-3">
            <AppIcon :icon="getAssetIcon(item.type).icon" :color="getAssetIcon(item.type).color" :size="18" class="shrink-0" />
            <span class="w-12 shrink-0 text-sm" style="color: var(--text-primary)">{{ getAssetIcon(item.type).label }}</span>
            <div class="sb-track h-1.5 min-w-0 flex-1 overflow-hidden" style="background: var(--bg-tertiary); border-radius: var(--radius-sm)">
              <div
                class="h-full"
                style="border-radius: var(--radius-sm)"
                :style="{ width: (item.value / Math.max(totalAssetValue, 1) * 100) + '%', background: getAssetIcon(item.type).color }"
              ></div>
            </div>
            <span class="w-20 shrink-0 text-right text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ item.value.toFixed(0) }}</span>
            <span class="w-10 shrink-0 text-right text-xs" style="color: var(--text-secondary)">{{ item.count }}项</span>
          </li>
        </ul>
      </section>
    </section>

    <!-- 二、最近发生什么：今日动态 -->
    <section aria-label="最近发生什么" class="grid gap-4 lg:grid-cols-2">
      <UCard class="sb-surface">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="sb-h text-base" style="color: var(--text-primary)">最近交易</h2>
          <NuxtLink to="/transactions" class="text-sm font-medium" style="color: var(--accent)">查看全部</NuxtLink>
        </div>
        <ul v-if="mounted && recentTransactions.length > 0" class="-mx-1 space-y-2">
          <li v-for="tx in recentTransactions" :key="tx.id">
            <NuxtLink
              to="/transactions"
              class="tx-row flex items-center gap-3 px-2 py-2"
              style="border-radius: var(--radius-md)"
            >
              <span
                class="flex h-9 w-9 shrink-0 items-center justify-center"
                style="border-radius: var(--radius-md)"
                :style="{ background: getCategoryIcon(tx.category).color + '20' }"
              >
                <AppIcon :icon="getCategoryIcon(tx.category).icon" :color="getCategoryIcon(tx.category).color" :size="20" />
              </span>
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm font-medium" style="color: var(--text-primary)">{{ tx.description || tx.category }}</span>
                <span class="mt-0.5 block text-xs" style="color: var(--text-secondary)">{{ getAccountName(tx.account) }} · {{ formatTime(tx.parsed_at) }}</span>
              </span>
              <span
                class="shrink-0 text-sm font-semibold tabular-nums"
                :style="{ color: tx.transaction_type === 'income' ? 'var(--success)' : 'var(--danger)' }"
              >
                {{ tx.transaction_type === 'income' ? '+' : '-' }}¥{{ tx.amount.toFixed(2) }}
              </span>
            </NuxtLink>
          </li>
        </ul>
        <p v-else class="py-8 text-center text-sm" style="color: var(--text-secondary)">还没有交易，记下第一笔支出或收入。</p>
      </UCard>

      <UCard class="sb-surface">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="sb-h text-base" style="color: var(--text-primary)">消费分类榜</h2>
          <NuxtLink to="/analysis" class="text-sm font-medium" style="color: var(--accent)">更多解读</NuxtLink>
        </div>
        <ul v-if="mounted && trend.categories.length > 0" class="space-y-2.5">
          <li v-for="cat in trend.categories" :key="cat.name">
            <NuxtLink
              :to="{ path: '/transactions', query: { category: cat.name } }"
              class="tx-row flex items-center gap-3 px-2 py-1.5"
              style="border-radius: var(--radius-md)"
            >
              <AppIcon :icon="getCategoryIcon(cat.name).icon" :color="getCategoryIcon(cat.name).color" :size="18" class="shrink-0" />
              <span class="w-16 shrink-0 truncate text-sm" style="color: var(--text-primary)">{{ cat.name }}</span>
              <span class="sb-track h-2 min-w-0 flex-1 overflow-hidden" style="background: var(--bg-tertiary); border-radius: var(--radius-sm)">
                <span
                  class="block h-full"
                  style="border-radius: var(--radius-sm)"
                  :style="{ width: (cat.amount / totalCategoryAmount * 100) + '%', background: getCategoryIcon(cat.name).color }"
                ></span>
              </span>
              <span class="w-20 shrink-0 text-right text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ cat.amount.toFixed(2) }}</span>
              <span class="w-12 shrink-0 text-right text-xs tabular-nums" style="color: var(--text-secondary)">{{ (cat.amount / totalCategoryAmount * 100).toFixed(1) }}%</span>
            </NuxtLink>
          </li>
        </ul>
        <p v-else class="py-8 text-center text-sm" style="color: var(--text-secondary)">近30天还没有支出分类。</p>
      </UCard>
    </section>

    <!-- 三、下一步干什么：CTA + 待办感 -->
    <section aria-label="下一步干什么" class="space-y-4">
      <div class="px-5 py-4 sm:px-6" style="background: var(--accent-soft); border-radius: var(--radius-lg)">
        <div class="flex flex-wrap items-center gap-3">
          <div class="mr-auto min-w-0">
            <h2 class="sb-h text-base" style="color: var(--text-primary)">今天，先记一笔</h2>
            <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">花了多少、进了多少，10 秒记下来，账就不会乱。</p>
          </div>
          <UButton to="/add" class="cta-press sb-cta">
            <AppIcon icon="Plus" :size="16" />
            记一笔
          </UButton>
        </div>
        <div v-if="liabilities.length > 0" class="mt-4 space-y-2 border-t pt-4" style="border-color: var(--border)">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-medium" style="color: var(--text-primary)">待办：还有 {{ liabilities.length }} 笔负债在还</h3>
            <UBadge color="neutral" variant="soft">{{ liabilities.slice(0, 3).length }} 项进行中</UBadge>
          </div>
          <ul class="space-y-2">
            <li v-for="l in liabilities.slice(0, 3)" :key="l.id" class="flex items-center gap-3">
              <AppIcon :icon="getLiabilityIcon(l.liability_type).icon" :color="getLiabilityIcon(l.liability_type).color" :size="16" class="shrink-0" />
              <span class="min-w-0 flex-1">
                <span class="block truncate text-sm" style="color: var(--text-primary)">{{ l.name }}</span>
                <span class="mt-1 block h-1 overflow-hidden" style="background: var(--bg-tertiary); border-radius: var(--radius-sm)">
                  <span
                    class="block h-full"
                    style="background: var(--success); border-radius: var(--radius-sm)"
                    :style="{ width: ((l.total_amount - l.current_amount) / Math.max(l.total_amount, 1) * 100) + '%' }"
                  ></span>
                </span>
              </span>
              <span class="shrink-0 text-sm font-medium tabular-nums" style="color: var(--text-primary)">
                ¥{{ l.current_amount.toFixed(0) }}<span class="font-normal" style="color: var(--text-secondary)">/¥{{ l.total_amount.toFixed(0) }}</span>
              </span>
            </li>
          </ul>
        </div>
      </div>

      <UCard v-if="mounted" class="sb-surface">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="sb-h text-base" style="color: var(--text-primary)">AI 洞察</h2>
          <UButton :loading="analyzing" variant="soft" color="neutral" class="cta-press" @click="analyze">
            {{ analyzing ? '分析中' : '立即分析' }}
          </UButton>
        </div>
        <div class="grid gap-6 md:grid-cols-3">
          <div>
            <div class="mb-1.5 flex items-center gap-1.5">
              <AppIcon icon="ChartLine" :size="18" style="color: var(--accent)" />
              <span class="sb-h text-sm" style="color: var(--text-primary)">消费分析</span>
            </div>
            <div class="insight-md text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderedAnalysis.consumption"></div>
          </div>
          <div>
            <div class="mb-1.5 flex items-center gap-1.5">
              <AppIcon icon="TrendUp" :size="18" style="color: var(--accent)" />
              <span class="sb-h text-sm" style="color: var(--text-primary)">投资分析</span>
            </div>
            <div class="insight-md text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderedAnalysis.investment"></div>
          </div>
          <div>
            <div class="mb-1.5 flex items-center gap-1.5">
              <AppIcon icon="BookOpen" :size="18" style="color: var(--accent)" />
              <span class="sb-h text-sm" style="color: var(--text-primary)">建议</span>
            </div>
            <div class="insight-md text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderedAnalysis.suggestion"></div>
          </div>
        </div>
      </UCard>

      <UCard v-if="mounted && monthly" class="sb-surface">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="sb-h text-base" style="color: var(--text-primary)">{{ monthly.year }}年{{ monthly.month }}月小结</h2>
          <UBadge color="neutral" variant="soft">储蓄率 {{ monthly.savings_rate }}%</UBadge>
        </div>
        <dl class="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">总收入</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" style="color: var(--success)">¥{{ monthly.total_income.toFixed(2) }}</dd>
          </div>
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">总支出</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" style="color: var(--danger)">¥{{ monthly.total_expense.toFixed(2) }}</dd>
          </div>
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">净收支</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" :style="{ color: monthly.net >= 0 ? 'var(--success)' : 'var(--danger)' }">¥{{ monthly.net.toFixed(2) }}</dd>
          </div>
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">日均支出</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ monthly.daily_avg_expense.toFixed(2) }}</dd>
          </div>
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">交易笔数</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" style="color: var(--text-primary)">{{ monthly.transaction_count }}</dd>
          </div>
          <div>
            <dt class="text-xs" style="color: var(--text-secondary)">储蓄率</dt>
            <dd class="mt-0.5 font-semibold tabular-nums" style="color: var(--text-primary)">{{ monthly.savings_rate }}%</dd>
          </div>
        </dl>
        <div v-if="monthly.weekly" class="mt-4 space-y-2 border-t pt-4" style="border-color: var(--border)">
          <h3 class="text-sm font-medium" style="color: var(--text-primary)">周对比</h3>
          <ul class="space-y-2">
            <li v-for="w in monthly.weekly" :key="w.week" class="flex items-center gap-3">
              <span class="w-12 shrink-0 text-xs" style="color: var(--text-secondary)">第{{ w.week }}周</span>
              <span class="flex min-w-0 flex-1 flex-col gap-1">
                <span
                  class="block h-1.5"
                  style="background: var(--success); border-radius: var(--radius-sm)"
                  :style="{ width: Math.min(w.income / Math.max(...monthly.weekly.map(x => x.income), 1) * 100, 100) + '%' }"
                ></span>
                <span
                  class="block h-1.5"
                  style="background: var(--danger); border-radius: var(--radius-sm)"
                  :style="{ width: Math.min(w.expense / Math.max(...monthly.weekly.map(x => x.expense), 1) * 100, 100) + '%' }"
                ></span>
              </span>
              <span class="w-32 shrink-0 text-right text-xs tabular-nums" style="color: var(--text-secondary)">入¥{{ w.income.toFixed(0) }} 出¥{{ w.expense.toFixed(0) }}</span>
            </li>
          </ul>
        </div>
      </UCard>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated, computed, watch } from 'vue'
import { renderMarkdown } from '~/composables/useMarkdown'
import { fetchDashboardStats, fetchLatestAnalysis, runAnalysis, fetchTrend, fetchMonthlyReport, fetchTransactions, fetchAssets, fetchLiabilities, fetchFxRates, fetchFxCurrencies } from '~/utils/api'
import { getCategoryIcon, getAssetIcon, getLiabilityIcon } from '~/utils/icons'
import { useECharts, axisCommon, tooltipCommon } from '~/composables/useECharts'
import { useCountUp } from '~/composables/useCountUp'

const stats = ref({
  net_assets: 0,
  total_assets: 0,
  total_liabilities: 0,
  total_account_balance: 0,
  monthly_income: 0,
  monthly_expenses: 0,
  transaction_count: 0
})

const analysis = ref({
  consumption: '点击"立即分析"获取 AI 建议',
  investment: '点击"立即分析"获取 AI 建议',
  suggestion: '点击"立即分析"获取 AI 建议'
})

const renderedAnalysis = computed(() => ({
  consumption: renderMarkdown(analysis.value.consumption || ''),
  investment: renderMarkdown(analysis.value.investment || ''),
  suggestion: renderMarkdown(analysis.value.suggestion || '')
}))

const analyzing = ref(false)
const mounted = ref(false)
const trendLoaded = ref(false)
// 首屏一次：入场 stagger 播完即撤掉 reveal，避免路由回来重播
const playEnter = ref(true)

// 展示币种（仅折算显示，账本仍记人民币；选择落盘，下次打开沿用）
const CURRENCY_KEY = 'sb-display-currency'
const displayCurrency = ref('CNY')
const currencyOptions = ref(['CNY'])
const fxSymbols = ref({ CNY: '¥' })
const fxRates = ref({})
const fxDate = ref('')

const currencyItems = computed(() =>
  currencyOptions.value.map(c => ({ label: `${fxSymbols.value[c] || ''} ${c}`, value: c }))
)

const fmtMoney = (v) => {
  const n = Number(v) || 0
  if (displayCurrency.value === 'CNY') return `¥${n.toFixed(2)}`
  const rate = fxRates.value[displayCurrency.value]
  if (!rate) return `¥${n.toFixed(2)}`
  const converted = n * rate
  const digits = displayCurrency.value === 'JPY' ? 0 : 2
  return `${fxSymbols.value[displayCurrency.value] || ''}${converted.toFixed(digits)}`
}

// stat 卡紧凑金额：绝对值过万用“万”缩写防截断（仅账户余额卡用）
const fmtCompactMoney = (v) => {
  const n = Number(v) || 0
  if (displayCurrency.value === 'CNY' && Math.abs(n) >= 10000) {
    const sign = n < 0 ? '-' : ''
    return `¥${sign}${(Math.abs(n) / 10000).toFixed(2)}万`
  }
  return fmtMoney(v)
}

const loadFx = async () => {
  try {
    if (currencyOptions.value.length <= 1) {
      const cur = await fetchFxCurrencies()
      currencyOptions.value = ['CNY', ...(cur.supported || [])]
      fxSymbols.value = { CNY: '¥', ...(cur.symbols || {}) }
    }
    if (displayCurrency.value === 'CNY') return
    const fx = await fetchFxRates('CNY', displayCurrency.value)
    fxRates.value = fx.rates || {}
    fxDate.value = fx.date || ''
  } catch (e) {
    console.error('加载汇率失败:', e)
  }
}

watch(displayCurrency, async (v) => {
  try {
    if (import.meta.client) localStorage.setItem(CURRENCY_KEY, v)
  } catch {}
  await loadFx()
  // 币种变化时以新格式重播 count-up（target 引用变化触发 useCountUp 内部 watch）
  stats.value = { ...stats.value }
})

// 首页 stat 数字 count-up：金额×5 + 整数×1，reduced-motion 下直接终值
const netAssets = useCountUp(() => Number(stats.value.net_assets) || 0, 'money', (v) => fmtMoney(v))
const totalAssets = useCountUp(() => Number(stats.value.total_assets) || 0, 'money', (v) => fmtCompactMoney(v))
const totalLiabilities = useCountUp(() => Number(stats.value.total_liabilities) || 0, 'money', (v) => fmtCompactMoney(v))
const monthlyExpenses = useCountUp(() => Number(stats.value.monthly_expenses) || 0, 'money', (v) => fmtMoney(v))
const monthlyIncome = useCountUp(() => Number(stats.value.monthly_income) || 0, 'money', (v) => fmtMoney(v))
const accountBalance = useCountUp(() => Number(stats.value.total_account_balance) || 0, 'money', (v) => fmtCompactMoney(v))
const txCount = useCountUp(() => Number(stats.value.transaction_count) || 0, 'int')

const statCards = computed(() => [
  { key: 'assets', label: '总资产', text: totalAssets.display.value, color: 'var(--success)' },
  { key: 'liab', label: '总负债', text: totalLiabilities.display.value, color: 'var(--danger)' },
  { key: 'acct', label: '账户余额', text: accountBalance.display.value, color: 'var(--text-primary)' },
  { key: 'exp', label: '本月支出', text: monthlyExpenses.display.value, color: 'var(--danger)' },
  { key: 'inc', label: '本月收入', text: monthlyIncome.display.value, color: 'var(--success)' },
  { key: 'count', label: '交易笔数', text: txCount.display.value, color: 'var(--text-primary)' },
])

const trend = ref({ daily: [], categories: [], total_expense: 0, total_income: 0 })
const monthly = ref(null)
const recentTransactions = ref([])
const assets = ref([])
const liabilities = ref([])

const trendDays = computed(() => trend.value.daily.length)
const totalCategoryAmount = computed(() => trend.value.categories.reduce((s, c) => s + c.amount, 0) || 1)

// 消费趋势：面积图置顶（支出/收入双面积，语义色），饼图只留分析页
const { el: trendEl, render: renderTrend } = useECharts()
watch(trend, (t) => {
  if (!t.daily.length) return
  renderTrend((p) => ({
    grid: { left: 8, right: 8, top: 28, bottom: 0, containLabel: true },
    tooltip: { ...tooltipCommon(p), valueFormatter: (v) => `¥${Number(v).toFixed(2)}` },
    legend: {
      top: 0, right: 0, textStyle: { color: p.subtext, fontSize: 11 },
      itemWidth: 12, itemHeight: 8,
    },
    xAxis: {
      type: 'category',
      data: t.daily.map((d) => d.date.slice(5)),
      ...axisCommon(p),
      axisLabel: { ...axisCommon(p).axisLabel, interval: Math.max(Math.floor(t.daily.length / 8) - 1, 0) },
    },
    yAxis: { type: 'value', ...axisCommon(p) },
    series: [
      {
        name: '支出', type: 'line', smooth: true, symbol: 'none',
        data: t.daily.map((d) => d.expense),
        lineStyle: { color: p.danger, width: 2 },
        areaStyle: { color: p.danger, opacity: 0.12 },
      },
      {
        name: '收入', type: 'line', smooth: true, symbol: 'none',
        data: t.daily.map((d) => d.income),
        lineStyle: { color: p.success, width: 2 },
        areaStyle: { color: p.success, opacity: 0.12 },
      },
    ],
  }))
}, { deep: true })

const loadStats = async () => {
  try {
    stats.value = await fetchDashboardStats()
  } catch (error) {
    console.error('加载统计失败:', error)
  }
}

const loadTrend = async () => {
  try {
    trend.value = await fetchTrend(30)
  } catch (error) {
    console.error('加载趋势失败:', error)
  } finally {
    trendLoaded.value = true
  }
}

const loadMonthly = async () => {
  try {
    monthly.value = await fetchMonthlyReport()
  } catch (error) {
    console.error('加载月报失败:', error)
  }
}

const loadAssets = async () => {
  try {
    const [a, l] = await Promise.all([fetchAssets(), fetchLiabilities()])
    assets.value = a.filter(x => x.status === 'active')
    liabilities.value = l.filter(x => x.status === 'active')
  } catch (error) {
    console.error('加载资产失败:', error)
  }
}

const totalAssetValue = computed(() => assets.value.reduce((s, a) => s + a.current_value, 0))
const totalLiabilityValue = computed(() => liabilities.value.reduce((s, l) => s + l.current_amount, 0))

const assetBreakdown = computed(() => {
  const groups = {}
  assets.value.forEach(a => {
    const t = a.asset_type || 'other'
    if (!groups[t]) groups[t] = { type: t, value: 0, count: 0 }
    groups[t].value += a.current_value
    groups[t].count++
  })
  return Object.values(groups).sort((a, b) => b.value - a.value)
})

const loadRecentTransactions = async () => {
  try {
    recentTransactions.value = await fetchTransactions({ limit: 10 })
  } catch (error) {
    console.error('加载最近交易失败:', error)
  }
}

const loadAnalysis = async () => {
  try {
    analysis.value = await fetchLatestAnalysis()
  } catch (error) {
    console.error('加载分析失败:', error)
  }
}

const analyze = async () => {
  analyzing.value = true
  try {
    analysis.value = await runAnalysis()
  } catch (error) {
    console.error('分析失败:', error)
    analysis.value = {
      consumption: '分析失败，请稍后重试',
      investment: '分析失败，请稍后重试',
      suggestion: '分析失败，请稍后重试'
    }
  } finally {
    analyzing.value = false
  }
}

const getAccountName = (account) => {
  const names = { cmb: '招商银行', icbc: '工商银行', ccb: '建设银行', abc: '农业银行', boc: '中国银行', bocom: '交通银行', spdb: '浦发银行', ceb: '光大银行', citic: '中信银行', unionpay: '云闪付', alipay: '支付宝', wechat_pay: '微信支付', meituan: '美团', jd: '京东', taobao: '淘宝', cash: '现金', other: '其他' }
  return names[account] || account
}

const formatTime = (time) => {
  const date = new Date(time)
  if (!mounted.value) return date.toLocaleDateString('zh-CN')
  const now = new Date()
  const diff = now - date
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)}天前`
  return date.toLocaleDateString('zh-CN')
}

const loadAll = () => {
  mounted.value = true
  loadStats()
  loadAnalysis()
  loadTrend()
  loadMonthly()
  loadRecentTransactions()
  loadAssets()
  loadFx()
}

onMounted(() => {
  try {
    if (import.meta.client) {
      const saved = localStorage.getItem(CURRENCY_KEY)
      if (saved) displayCurrency.value = saved
    }
  } catch {}
  loadAll()
  // 首屏一次：stagger 播完撤掉 reveal，后续切回来不再重播
  setTimeout(() => { playEnter.value = false }, 1200)
})
onActivated(loadAll) // 客户端路由导航回来时也重新加载
</script>

<style scoped>
/* ink 品牌金额标题用衬线展示字体，其他品牌回退继承，不引入新字 */
.brand-display {
  font-family: var(--font-brand-display);
}

/* CTA 按压缩放；只动 transform，不新增颜色 */
.cta-press {
  transition: transform 0.12s ease-out;
}
.cta-press:active {
  transform: scale(0.96);
}

/* 行 hover 只用品牌柔光底，不引入新色 */
.tx-row {
  transition: background-color 0.15s ease;
}
.tx-row:hover {
  background: var(--accent-soft);
}

/* AI 洞察 markdown 富文本：沿用原排版比例，颜色只用文本变量 */
.insight-md :deep(p) {
  margin: 0.5rem 0;
}
.insight-md :deep(p):first-child {
  margin-top: 0;
}
.insight-md :deep(ul),
.insight-md :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.25rem;
}
.insight-md :deep(li) {
  margin: 0.25rem 0;
}
.insight-md :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}
.insight-md :deep(code) {
  background: var(--bg-tertiary);
  padding: 0.1rem 0.3rem;
  border-radius: var(--radius-sm);
  font-size: 0.85em;
}
.insight-md :deep(h1),
.insight-md :deep(h2),
.insight-md :deep(h3) {
  color: var(--text-primary);
  margin: 0.75rem 0 0.35rem;
  font-size: 0.95em;
}

/* 键盘焦点：描边即时出现，零动画 */
a:focus-visible,
button:focus-visible {
  transition: none;
}

@media (prefers-reduced-motion: reduce) {
  .cta-press,
  .tx-row {
    transition: none;
  }
  .cta-press:active {
    transform: none;
  }
}
</style>

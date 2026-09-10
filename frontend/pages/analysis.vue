<template>
  <div class="mx-auto min-w-0 w-full max-w-5xl px-4 py-6">
    <!-- 页头：标题 + 模式 + 运行分析（CTA 置顶，loading 防连点） -->
    <div class="sticky top-0 z-10 -mx-4 px-4 py-3">
      <div class="flex flex-wrap items-center gap-3 rounded-lg px-3 py-2" style="background: var(--bg-primary); border: 1px solid var(--border)">
        <div class="mr-auto min-w-0">
          <h1 class="sb-h text-xl font-semibold" style="color: var(--text-primary)">AI 分析</h1>
          <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">消费、投资、建议三部分，附一张分类占比。</p>
        </div>
        <UBadge v-if="analysisMode" color="neutral" variant="soft">{{ modeLabel }}</UBadge>
        <UButton :loading="analyzing" :disabled="analyzing" @click="analyze">
          {{ analyzing ? '分析中' : '运行分析' }}
        </UButton>
      </div>
    </div>

    <!-- 分析中：骨架 -->
    <div v-if="analyzing" class="mt-6 space-y-4">
      <p class="text-sm" style="color: var(--text-secondary)">{{ loadingText }}</p>
      <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <UCard class="sb-surface"
          v-for="i in 3"
          :key="i"
          :ui="{ body: 'p-5' }"
        >
          <USkeleton class="h-5 w-24" />
          <USkeleton class="mt-3 h-4 w-full" />
          <USkeleton class="mt-2 h-4 w-11/12" />
          <USkeleton class="mt-2 h-4 w-4/5" />
          <USkeleton class="mt-2 h-4 w-3/5" />
        </UCard>
      </div>
    </div>

    <!-- 分析结果：结论 → 图 → 长文 -->
    <div v-else class="mt-6 space-y-6">
      <!-- ① 顶部结论卡：一句话 + 3 个数字 chips -->
      <UCard class="sb-surface"
        v-if="conclusionSentence"
        :ui="{ body: 'p-5' }"
      >
        <p class="text-sm font-medium leading-relaxed" style="color: var(--text-primary)">{{ conclusionSentence }}</p>
        <div class="mt-3 flex flex-wrap gap-2">
          <UBadge color="neutral" variant="soft">
            本月支出&nbsp;<span class="font-semibold tabular-nums">¥{{ totalExpense.toFixed(0) }}</span>
          </UBadge>
          <UBadge color="neutral" variant="soft">
            本月收入&nbsp;<span class="font-semibold tabular-nums">¥{{ monthlyIncome.toFixed(0) }}</span>
          </UBadge>
          <UBadge color="neutral" variant="soft">
            储蓄率&nbsp;<span class="font-semibold tabular-nums">{{ savingsRate.toFixed(1) }}%</span>
          </UBadge>
        </div>
      </UCard>

      <!-- 分类饼图：图例悬停高亮，扇区点击穿透到交易页 -->
      <UCard class="sb-surface"
        v-if="categoryStats.length > 0"
        :ui="{ body: 'p-5' }"
      >
        <h3 class="sb-h mb-3 text-base font-semibold" style="color: var(--text-primary)">消费分类</h3>
        <div class="flex flex-wrap items-center gap-6">
          <div ref="pieEl" class="h-[220px] w-[220px] min-w-[220px] shrink-0 cursor-pointer" role="img" aria-label="消费分类占比图"></div>
          <ul class="min-w-[200px] flex-1 space-y-1.5">
            <li v-for="(cat, i) in categoryStats.slice(0, 8)" :key="cat.name">
              <button
                type="button"
                class="legend-btn flex w-full items-center gap-2 rounded-md px-2 py-1 text-left"
                :aria-label="`高亮${cat.name}`"
                @click="focusSlice(i)"
                @mouseenter="focusSlice(i)"
              >
                <span class="h-3 w-3 shrink-0 rounded-[3px]" :style="{ background: pieColors[i % pieColors.length] }"></span>
                <span class="min-w-[60px] text-sm" style="color: var(--text-primary)">{{ cat.name }}</span>
                <span class="text-sm font-medium tabular-nums" style="color: var(--text-primary)">¥{{ cat.amount.toFixed(0) }}</span>
                <span class="text-xs tabular-nums" style="color: var(--text-secondary)">{{ ((cat.amount / totalExpense) * 100).toFixed(1) }}%</span>
              </button>
            </li>
          </ul>
        </div>
      </UCard>

      <!-- ② 三块解读：UCollapsible 折叠，默认展开第一块 -->
      <div v-if="analysis.consumption || analysis.investment || analysis.suggestion" class="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <UCollapsible v-model:open="openConsumption">
            <UButton color="neutral" variant="ghost" block class="justify-between">
              <span class="flex items-center gap-2">
                <AppIcon icon="ChartLine" :size="20" style="color: var(--accent)" />
                <span class="sb-h text-base font-semibold" style="color: var(--text-primary)">消费分析</span>
              </span>
            </UButton>
            <template #content>
              <div class="markdown-body mt-2 text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderMd(analysis.consumption)"></div>
            </template>
          </UCollapsible>
        </UCard>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <UCollapsible v-model:open="openInvestment">
            <UButton color="neutral" variant="ghost" block class="justify-between">
              <span class="flex items-center gap-2">
                <AppIcon icon="TrendUp" :size="20" style="color: var(--accent)" />
                <span class="sb-h text-base font-semibold" style="color: var(--text-primary)">投资分析</span>
              </span>
            </UButton>
            <template #content>
              <div class="markdown-body mt-2 text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderMd(analysis.investment)"></div>
            </template>
          </UCollapsible>
        </UCard>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <UCollapsible v-model:open="openSuggestion">
            <UButton color="neutral" variant="ghost" block class="justify-between">
              <span class="flex items-center gap-2">
                <AppIcon icon="BookOpen" :size="20" style="color: var(--accent)" />
                <span class="sb-h text-base font-semibold" style="color: var(--text-primary)">综合建议</span>
              </span>
            </UButton>
            <template #content>
              <div class="markdown-body mt-2 text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderMd(analysis.suggestion)"></div>
            </template>
          </UCollapsible>
        </UCard>
      </div>

      <!-- ④ 历史分析：时间线排布，点击展开全文 -->
      <UCard class="sb-surface"
        v-if="history.length > 0"
        :ui="{ body: 'p-5' }"
      >
        <h2 class="sb-h mb-3 text-base font-semibold" style="color: var(--text-primary)">历史分析</h2>
        <ol class="relative space-y-5 border-l pl-5" style="border-color: var(--border)">
          <li v-for="batch in history" :key="batch.created_at" class="relative">
            <span class="absolute top-1.5 h-2.5 w-2.5 rounded-full" style="background: var(--accent); left: -26px"></span>
            <div class="flex flex-wrap items-center gap-2">
              <span class="text-xs tabular-nums" style="color: var(--text-secondary)">{{ formatTime(batch.created_at) }}</span>
              <UBadge v-if="batch.items && batch.items[0]" color="neutral" variant="soft">{{ batch.items[0].agent_name }}</UBadge>
            </div>
            <div class="mt-2 space-y-1.5">
              <UCollapsible v-for="item in batch.items" :key="item.id">
                <UButton color="neutral" variant="ghost" block class="justify-start">
                  <span class="min-w-0 flex flex-1 items-center gap-3 text-left">
                    <span class="shrink-0 text-xs font-medium" style="color: var(--accent)">{{ typeLabels[item.analysis_type] || item.analysis_type }}</span>
                    <span class="min-w-0 flex-1 truncate text-xs font-normal" style="color: var(--text-secondary)">{{ stripMd(item.content).substring(0, 80) }}...</span>
                  </span>
                </UButton>
                <template #content>
                  <div class="mt-1 rounded-lg px-3 py-2" :style="{ background: 'var(--bg-primary)', border: '1px solid var(--border)' }">
                    <div class="markdown-body text-sm leading-relaxed" style="color: var(--text-secondary)" v-html="renderMd(item.content)"></div>
                    <UButton class="mt-2" size="xs" color="neutral" variant="soft" @click="loadHistory(item)">载入为当前解读</UButton>
                  </div>
                </template>
              </UCollapsible>
            </div>
          </li>
        </ol>
      </UCard>

      <!-- 无数据 -->
      <UCard
        v-if="!analysis.consumption"
        class="sb-surface text-center"
        :ui="{ body: 'p-8' }"
      >
        <AppIcon icon="ChartLine" :size="32" style="color: var(--text-tertiary)" class="mx-auto" />
        <p class="sb-h mt-3 text-sm font-medium" style="color: var(--text-primary)">还没有分析结果</p>
        <p class="mt-1 text-sm" style="color: var(--text-secondary)">点右上角「运行分析」，先出一份看看。</p>
        <UButton class="mt-4" :loading="analyzing" :disabled="analyzing" @click="analyze">运行分析</UButton>
      </UCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, computed, watch, nextTick } from 'vue'
import { marked } from 'marked'
import sanitizeHtml from 'sanitize-html'
import { renderMarkdown } from '~/composables/useMarkdown'
import * as echarts from 'echarts'
import { useRouter } from 'vue-router'
import { runAnalysis, fetchLatestAnalysis, fetchAnalysisHistory, fetchMonthlyStats } from '~/utils/api'

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

const router = useRouter()

const renderMd = (text: string) => {
  if (!text) return ''
  return renderMarkdown(text)
}

const stripMd = (text: string) => {
  if (!text) return ''
  return text.replace(/[#*_`~\[\]()>]/g, '').replace(/\n+/g, ' ').trim()
}

const analyzing = ref(false)
const analysisMode = ref('')
const analysis = ref({
  consumption: '',
  investment: '',
  suggestion: ''
})
const history = ref([])
const clientReady = ref(false)
const loadingText = ref('正在整理你的收支，请稍候…')
const categoryStats = ref([])
const totalExpense = ref(0)
const monthlyIncome = ref(0)
const savingsRate = ref(0)
const pieColors = ['#0F766E', '#3B82F6', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#6366F1']

// 解读折叠：默认展开第一块
const openConsumption = ref(true)
const openInvestment = ref(false)
const openSuggestion = ref(false)

// 顶部结论：解读首段一句话
const conclusionSentence = computed(() => {
  const raw = analysis.value.consumption || analysis.value.investment || analysis.value.suggestion || ''
  if (!raw) return ''
  const plain = stripMd(raw).replace(/\s+/g, ' ').trim()
  if (!plain) return ''
  const m = plain.match(/^[^。！？.!?]+[。！？.!?]?/)
  return (m ? m[0] : plain.slice(0, 60)).trim()
})

// 上次分析结果缓存：先显示旧的，再拉新的（客户端 localStorage）
const ANALYSIS_CACHE_KEY = 'sb-analysis-cache'
const hydrateCache = () => {
  if (!import.meta.client) return
  try {
    const raw = localStorage.getItem(ANALYSIS_CACHE_KEY)
    if (!raw) return
    const cached = JSON.parse(raw)
    if (cached && (cached.consumption || cached.investment)) {
      analysis.value = {
        consumption: cached.consumption || '',
        investment: cached.investment || '',
        suggestion: cached.suggestion || '',
      }
      analysisMode.value = cached.mode || ''
    }
  } catch {}
}
const saveCache = () => {
  if (!import.meta.client) return
  try {
    localStorage.setItem(ANALYSIS_CACHE_KEY, JSON.stringify({ ...analysis.value, mode: analysisMode.value }))
  } catch {}
}

// 分类饼图 echarts（颜色与 legend 圆点同源）
const { el: pieEl, render: renderPie } = useECharts()
watch([categoryStats, totalExpense], () => {
  if (!categoryStats.value.length) return
  renderPie((p) => ({
    tooltip: {
      trigger: 'item',
      backgroundColor: p.bg,
      borderColor: p.border,
      textStyle: { color: p.text, fontSize: 12 },
      valueFormatter: (v) => `¥${Number(v).toFixed(0)}`,
    },
    series: [
      {
        type: 'pie',
        radius: ['45%', '70%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: p.bg, borderWidth: 2, borderRadius: 4 },
        label: { show: false },
        emphasis: { scale: true, scaleSize: 4 },
        data: categoryStats.value.slice(0, 8).map((cat, i) => ({
          name: cat.name,
          value: cat.amount,
          itemStyle: { color: pieColors[i % pieColors.length] },
        })),
      },
    ],
  }))
  nextTick(() => {
    if (!pieEl.value) return
    const chart = echarts.getInstanceByDom(pieEl.value)
    if (!chart) return
    chart.off('click')
    chart.on('click', (params: any) => {
      const cat = categoryStats.value.slice(0, 8)[params.dataIndex] || { name: params.name, amount: params.value }
      goCategory(cat)
    })
  })
})

// 饼图扇区点击穿透：金额 0 的扇区不跳
const goCategory = (cat: any) => {
  if (!cat || !cat.name || Number(cat.amount) === 0) return
  router.push({ path: '/transactions', query: { category: cat.name } })
}

// 图例可点：点中/悬停即高亮对应扇区并弹出提示
const focusSlice = (i: number) => {
  if (!pieEl.value) return
  const chart = echarts.getInstanceByDom(pieEl.value)
  if (!chart) return
  chart.dispatchAction({ type: 'downplay', seriesIndex: 0 })
  chart.dispatchAction({ type: 'highlight', seriesIndex: 0, dataIndex: i })
  chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: i })
}

const typeLabels = {
  consumption: '消费',
  investment: '投资',
  suggestion: '建议'
}

const modeLabel = computed(() => {
  const m = analysisMode.value
  if (m === 'openclaw') return 'OpenClaw Agent'
  if (m === 'local') return '本地 LLM'
  if (m.includes('fallback')) return '💻 本地 (fallback)'
  return m
})

const analyze = async () => {
  analyzing.value = true
  loadingText.value = '正在请 Agent 看账，请稍候…'
  try {
    const result = await runAnalysis()
    analysis.value = result
    analysisMode.value = result.mode || 'local'
    saveCache()
  } catch (error) {
    console.error('分析失败:', error)
    analysis.value = {
      consumption: '分析失败，请检查 Agent 服务状态',
      investment: '',
      suggestion: ''
    }
  } finally {
    analyzing.value = false
  }
}

const loadHistory = (item) => {
  if (item.analysis_type === 'consumption') analysis.value.consumption = item.content
  if (item.analysis_type === 'investment') analysis.value.investment = item.content
  if (item.analysis_type === 'suggestion') analysis.value.suggestion = item.content
}

const formatTime = (t) => {
  if (!t) return ''
  const date = new Date(t)
  if (!clientReady.value) return date.toLocaleDateString('zh-CN')
  return date.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const loadError = ref('')

const loadAll = async () => {
  // 仅在客户端加载（SSR 没有 auth token）
  if (import.meta.server) return
  loadError.value = ''

  // 独立加载每个数据源，避免一个失败影响其他
  try {
    const data = await fetchLatestAnalysis()
    if (data && (data.consumption || data.investment)) {
      analysis.value = data
      analysisMode.value = data.mode || 'local'
      saveCache()
    }
  } catch (e) {
    console.error('加载分析数据失败:', e)
  }

  try {
    const hist = await fetchAnalysisHistory(10)
    if (hist) history.value = hist
  } catch (e) {
    console.error('加载历史失败:', e)
  }

  // 加载分类统计
  try {
    const monthly = await fetchMonthlyStats()
    if (monthly && monthly.expense_categories) {
      categoryStats.value = monthly.expense_categories
      totalExpense.value = monthly.total_expense || 0
      monthlyIncome.value = monthly.total_income || 0
      savingsRate.value = typeof monthly.savings_rate === 'number' ? monthly.savings_rate : 0
    }
  } catch (e) {
    console.error('加载分类统计失败:', e)
  }
}
onMounted(() => { clientReady.value = true; hydrateCache(); loadAll() })
onActivated(() => { clientReady.value = true; loadAll() })
</script>

<style scoped>
/* 图例/历史行 hover 只用品牌柔光底，不引入新色 */
.legend-btn {
  transition: background-color 0.15s ease;
}
.legend-btn:hover {
  background: var(--accent-soft);
}

/* Markdown 渲染样式（v-html 内容，颜色只用文本变量） */
.markdown-body :deep(h1) { font-size: 1.4rem; color: var(--text-primary); margin: 1rem 0 0.5rem; font-weight: 600; }
.markdown-body :deep(h2) { font-size: 1.2rem; color: var(--text-primary); margin: 0.8rem 0 0.4rem; font-weight: 600; }
.markdown-body :deep(h3) { font-size: 1.05rem; color: var(--text-primary); margin: 0.6rem 0 0.3rem; font-weight: 600; }
.markdown-body :deep(p) { margin: 0.4rem 0; }
.markdown-body :deep(ul), .markdown-body :deep(ol) { padding-left: 1.5rem; margin: 0.4rem 0; }
.markdown-body :deep(li) { margin: 0.2rem 0; }
.markdown-body :deep(strong) { color: var(--text-primary); font-weight: 600; }
.markdown-body :deep(em) { font-style: italic; }
.markdown-body :deep(code) { background: rgba(180,83,9,0.1); padding: 0.15rem 0.4rem; border-radius: 4px; font-size: 0.85em; }
.markdown-body :deep(pre) { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; overflow-x: auto; margin: 0.5rem 0; }
.markdown-body :deep(pre code) { background: none; padding: 0; }
.markdown-body :deep(blockquote) { border-left: 3px solid var(--accent); padding-left: 1rem; margin: 0.5rem 0; color: var(--text-secondary); }
.markdown-body :deep(table) { width: 100%; border-collapse: collapse; margin: 0.5rem 0; }
.markdown-body :deep(th), .markdown-body :deep(td) { border: 1px solid var(--border); padding: 0.4rem 0.75rem; text-align: left; }
.markdown-body :deep(th) { background: var(--bg-primary); font-weight: 600; color: var(--text-primary); }
.markdown-body :deep(hr) { border: none; border-top: 1px solid var(--border); margin: 1rem 0; }
.markdown-body :deep(a) { color: var(--accent); text-decoration: underline; }

@media (prefers-reduced-motion: reduce) {
  .legend-btn {
    transition: none;
  }
}

/* 480px：收紧卡片内边距，时间线不错位 */
@media (max-width: 480px) {
  ol.border-l {
    margin-left: 2px;
  }
}
</style>

<template>
  <div class="container">
    <div class="header">
      <h1>AI 分析</h1>
      <div class="header-actions">
        <span v-if="analysisMode" class="mode-badge" :class="analysisMode">
          {{ modeLabel }}
        </span>
        <button @click="analyze" class="btn btn-primary" :disabled="analyzing">
          {{ analyzing ? '分析中...' : '运行分析' }}
        </button>
      </div>
    </div>

    <!-- 分析中 -->
    <div v-if="analyzing" class="loading-state">
      <div class="spinner"></div>
      <p>{{ loadingText }}</p>
    </div>

    <!-- 分析结果 -->
    <div v-else class="analysis-content">
      <div class="analysis-grid">
        <div class="analysis-card">
          <div class="card-header">
            <span class="card-icon">💸</span>
            <h2>消费分析</h2>
            <span v-if="analysisMode === 'openclaw'" class="agent-badge">墨砚</span>
          </div>
          <div class="card-content">{{ analysis.consumption }}</div>
        </div>

        <div class="analysis-card">
          <div class="card-header">
            <span class="card-icon">📈</span>
            <h2>投资分析</h2>
            <span v-if="analysisMode === 'openclaw'" class="agent-badge">远瞻</span>
          </div>
          <div class="card-content">{{ analysis.investment }}</div>
        </div>

        <div class="analysis-card">
          <div class="card-header">
            <span class="card-icon">💡</span>
            <h2>综合建议</h2>
          </div>
          <div class="card-content">{{ analysis.suggestion }}</div>
        </div>
      </div>

      <!-- 图表区 -->
      <div v-if="categoryStats.length > 0" class="charts-section">
        <div class="chart-card">
          <h3>📊 消费分类</h3>
          <div class="pie-chart-wrapper">
            <div class="css-pie" :style="pieStyle"></div>
            <div class="pie-legend">
              <div v-for="(cat, i) in categoryStats.slice(0, 8)" :key="cat.name" class="legend-item">
                <span class="legend-dot" :style="{ background: pieColors[i % pieColors.length] }"></span>
                <span class="legend-name">{{ cat.name }}</span>
                <span class="legend-value">¥{{ cat.amount.toFixed(0) }}</span>
                <span class="legend-pct">{{ ((cat.amount / totalExpense) * 100).toFixed(1) }}%</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 历史分析 -->
      <div v-if="history.length > 0" class="history-section">
        <h2>📜 历史分析</h2>
        <div class="history-list">
          <div v-for="batch in history" :key="batch.created_at" class="history-batch">
            <div class="history-time">{{ formatTime(batch.created_at) }}</div>
            <div class="history-items">
              <div v-for="item in batch.items" :key="item.id" class="history-item" @click="loadHistory(item)">
                <span class="history-type">{{ typeLabels[item.analysis_type] || item.analysis_type }}</span>
                <span class="history-preview">{{ item.content.substring(0, 80) }}...</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 无数据 -->
    <div v-if="!analyzing && !analysis.consumption" class="empty-state">
      <p>暂无分析数据，点击「运行分析」开始</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated, computed } from 'vue'
import { runAnalysis, fetchLatestAnalysis, fetchAnalysisHistory } from '~/utils/api'
import { getCategoryIcon } from '~/utils/icons'

const analyzing = ref(false)
const analysisMode = ref('')
const analysis = ref({
  consumption: '',
  investment: '',
  suggestion: ''
})
const history = ref([])
const clientReady = ref(false)
const loadingText = ref('AI 正在分析您的财务数据...')
const categoryStats = ref([])
const totalExpense = ref(0)
const pieColors = ['#b45309', '#3B82F6', '#10B981', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899', '#6366F1']

const pieStyle = computed(() => {
  if (!categoryStats.value.length) return ''
  let acc = 0
  const segments = categoryStats.value.slice(0, 8).map((cat, i) => {
    const pct = (cat.amount / totalExpense.value) * 100
    const start = acc
    acc += pct
    return `${pieColors[i % pieColors.length]} ${start}% ${acc}%`
  })
  return `background: conic-gradient(${segments.join(', ')})`
})

const typeLabels = {
  consumption: '消费',
  investment: '投资',
  suggestion: '建议'
}

const modeLabel = computed(() => {
  const m = analysisMode.value
  if (m === 'openclaw') return '🔌 OpenClaw Agent'
  if (m === 'local') return '💻 本地 LLM'
  if (m.includes('fallback')) return '💻 本地 (fallback)'
  return m
})

const analyze = async () => {
  analyzing.value = true
  loadingText.value = '正在调用 Agent 分析...'
  try {
    const result = await runAnalysis()
    analysis.value = result
    analysisMode.value = result.mode || 'local'
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

const loadAll = async () => {
  try {
    const [data, hist] = await Promise.all([fetchLatestAnalysis(), fetchAnalysisHistory(10)])
    if (data && (data.consumption || data.investment)) {
      analysis.value = data
      analysisMode.value = data.mode || 'local'
    }
    if (hist) history.value = hist
    
    // 加载分类统计
    try {
      const config = useRuntimeConfig()
      const apiBase = config.public?.apiBase || '/api'
      const monthly = await $fetch(`${apiBase}/stats/monthly`)
      if (monthly && monthly.expense_categories) {
        categoryStats.value = monthly.expense_categories
        totalExpense.value = monthly.total_expense || 0
      }
    } catch (e) {
      console.error('加载分类统计失败:', e)
    }
  } catch (e) {
    console.error('加载失败:', e)
  }
}
onMounted(() => { setTimeout(() => { clientReady.value = true }, 0); loadAll() })
onActivated(() => { setTimeout(() => { clientReady.value = true }, 0); loadAll() })
</script>

<style scoped>
.container { max-width: 1200px; margin: 0 auto; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 2rem; }
.header h1 { font-size: 1.8rem; color: var(--accent); }
.header-actions { display: flex; align-items: center; gap: 0.75rem; }
.mode-badge { padding: 0.25rem 0.75rem; border-radius: 6px; font-size: 0.8rem; font-weight: 500; }
.mode-badge.openclaw { background: rgba(180,83,9,0.15); color: var(--accent); }
.mode-badge.local { background: rgba(59,130,246,0.15); color: #3B82F6; }
.btn { padding: 0.5rem 1.5rem; border: none; border-radius: 8px; cursor: pointer; font-weight: 500; }
.btn-primary { background: var(--accent); color: white; }
.btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.loading-state { text-align: center; padding: 4rem; color: var(--text-secondary); }
.spinner { width: 40px; height: 40px; border: 3px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 1rem; }
@keyframes spin { to { transform: rotate(360deg); } }
.analysis-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }
.analysis-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
.analysis-card:hover { border-color: var(--accent); }
.card-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 1rem; }
.card-icon { font-size: 1.5rem; }
.card-header h2 { font-size: 1.2rem; color: var(--text-primary); flex: 1; }
.agent-badge { background: rgba(180,83,9,0.15); color: var(--accent); padding: 0.15rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
.card-content { color: var(--text-secondary); line-height: 1.7; white-space: pre-wrap; }
.history-section h2 { color: var(--text-primary); margin-bottom: 1rem; }
.history-list { display: flex; flex-direction: column; gap: 0.5rem; }
.history-item { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 8px; padding: 0.75rem 1rem; display: flex; gap: 1rem; cursor: pointer; transition: all 0.15s; }
.history-item:hover { border-color: var(--accent); }
.history-time { color: var(--text-secondary); font-size: 0.85rem; min-width: 120px; }
.history-type { color: var(--accent); font-size: 0.85rem; min-width: 60px; }
.history-preview { color: var(--text-secondary); font-size: 0.85rem; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-state { text-align: center; padding: 4rem; color: var(--text-secondary); }

.charts-section { margin-bottom: 2rem; }
.chart-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; }
.chart-card h3 { color: var(--text-primary); margin-bottom: 1rem; }
.pie-chart-wrapper { display: flex; gap: 2rem; align-items: center; flex-wrap: wrap; }
.css-pie { width: 200px; height: 200px; border-radius: 50%; min-width: 200px; }
.pie-legend { flex: 1; display: flex; flex-direction: column; gap: 0.4rem; min-width: 200px; }
.legend-item { display: flex; align-items: center; gap: 0.5rem; }
.legend-dot { width: 12px; height: 12px; border-radius: 3px; flex-shrink: 0; }
.legend-name { color: var(--text-primary); font-size: 0.85rem; min-width: 60px; }
.legend-value { color: var(--text-primary); font-size: 0.85rem; font-weight: 500; }
.legend-pct { color: var(--text-secondary); font-size: 0.8rem; }
</style>

/* 响应式适配 */
@media (max-width: 768px) {
  .container {
    padding: 1rem;
  }
  .grid {
    grid-template-columns: 1fr !important;
  }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 480px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }
}

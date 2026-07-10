<template>
  <div class="container">
    <div class="hero">
      <h1>SilentBook</h1>
      <p class="tagline">财务自由，不是终点，是每一步的选择。</p>
    </div>
    
    <!-- 核心指标 -->
    <div class="stats">
      <div class="stat-card">
        <div class="stat-label">净资产</div>
        <div class="stat-value">¥{{ stats.net_assets.toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">总资产</div>
        <div class="stat-value income">¥{{ (stats.total_assets || 0).toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">总负债</div>
        <div class="stat-value expense">¥{{ (stats.total_liabilities || 0).toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">本月支出</div>
        <div class="stat-value expense">¥{{ stats.monthly_expenses.toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">本月收入</div>
        <div class="stat-value income">¥{{ stats.monthly_income.toFixed(2) }}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">交易笔数</div>
        <div class="stat-value">{{ stats.transaction_count }}</div>
      </div>
    </div>

    <!-- AI 洞察 -->
    <div class="ai-section">
      <div class="section-header">
        <h2>🤖 AI 洞察</h2>
        <button @click="analyze" class="btn btn-primary" :disabled="analyzing">
          {{ analyzing ? '分析中...' : '立即分析' }}
        </button>
      </div>
      
      <div class="insights">
        <div class="insight-card">
          <div class="insight-header">
            <span class="insight-icon">💸</span>
            <span class="insight-title">消费分析</span>
          </div>
          <div class="insight-content" v-html="renderedAnalysis.consumption"></div>
        </div>
        
        <div class="insight-card">
          <div class="insight-header">
            <span class="insight-icon">📈</span>
            <span class="insight-title">投资分析</span>
          </div>
          <div class="insight-content" v-html="renderedAnalysis.investment"></div>
        </div>
        
        <div class="insight-card">
          <div class="insight-header">
            <span class="insight-icon">💡</span>
            <span class="insight-title">建议</span>
          </div>
          <div class="insight-content" v-html="renderedAnalysis.suggestion"></div>
        </div>
      </div>
    </div>

    <!-- 资产概览 -->
    <div class="asset-section" v-if="assets.length > 0 || liabilities.length > 0">
      <div class="section-header">
        <h2>🏦 资产概览</h2>
        <NuxtLink to="/assets" class="view-all">管理资产 →</NuxtLink>
      </div>
      <div class="asset-summary">
        <div class="asset-bar-row">
          <div class="asset-bar-label">净资产</div>
          <div class="asset-bar-value" :class="(totalAssetValue - totalLiabilityValue) >= 0 ? 'income' : 'expense'">
            ¥{{ (totalAssetValue - totalLiabilityValue).toFixed(2) }}
          </div>
        </div>
        <div class="asset-compare-bar">
          <div class="asset-fill asset-green" :style="{ width: (totalAssetValue / Math.max(totalAssetValue + totalLiabilityValue, 1) * 100) + '%' }">
            <span v-if="totalAssetValue > 0">资产 ¥{{ totalAssetValue.toFixed(0) }}</span>
          </div>
          <div class="asset-fill asset-red" :style="{ width: (totalLiabilityValue / Math.max(totalAssetValue + totalLiabilityValue, 1) * 100) + '%' }">
            <span v-if="totalLiabilityValue > 0">负债 ¥{{ totalLiabilityValue.toFixed(0) }}</span>
          </div>
        </div>
      </div>
      <!-- 资产分类明细 -->
      <div class="asset-breakdown" v-if="assetBreakdown.length > 0">
        <div v-for="item in assetBreakdown" :key="item.type" class="asset-detail-item">
          <span class="asset-detail-icon">{{ getAssetIcon(item.type).icon }}</span>
          <span class="asset-detail-name">{{ getAssetIcon(item.type).label }}</span>
          <div class="asset-detail-bar-bg">
            <div class="asset-detail-bar-fill" :style="{ width: (item.value / Math.max(totalAssetValue, 1) * 100) + '%', background: getAssetIcon(item.type).color }"></div>
          </div>
          <span class="asset-detail-amount">¥{{ item.value.toFixed(0) }}</span>
          <span class="asset-detail-count">{{ item.count }}项</span>
        </div>
      </div>
      <!-- 负债列表 -->
      <div class="liability-mini" v-if="liabilities.length > 0">
        <div class="liability-mini-title">📋 负债进度</div>
        <div v-for="l in liabilities.slice(0, 3)" :key="l.id" class="liability-mini-item">
          <span class="liability-mini-icon">{{ getLiabilityIcon(l.liability_type).icon }}</span>
          <div class="liability-mini-info">
            <div class="liability-mini-name">{{ l.name }}</div>
            <div class="liability-mini-bar">
              <div class="liability-mini-fill" :style="{ width: ((l.total_amount - l.current_amount) / Math.max(l.total_amount, 1) * 100) + '%' }"></div>
            </div>
          </div>
          <span class="liability-mini-amount">¥{{ l.current_amount.toFixed(0) }}<span class="liability-mini-total">/¥{{ l.total_amount.toFixed(0) }}</span></span>
        </div>
      </div>
    </div>

    <!-- 最近交易 -->
    <div class="recent-section" v-if="recentTransactions.length > 0">
      <div class="section-header">
        <h2>💸 最近交易</h2>
        <NuxtLink to="/transactions" class="view-all">查看全部 →</NuxtLink>
      </div>
      <div class="recent-list">
        <div v-for="tx in recentTransactions" :key="tx.id" class="recent-item">
          <div class="recent-icon" :style="{ background: getCategoryIcon(tx.category).color + '20' }">
            <span>{{ getCategoryIcon(tx.category).icon }}</span>
          </div>
          <div class="recent-info">
            <div class="recent-desc">{{ tx.description || tx.category }}</div>
            <div class="recent-meta">
              <span>{{ getAccountName(tx.account) }}</span>
              <span>·</span>
              <span>{{ formatTime(tx.parsed_at) }}</span>
            </div>
          </div>
          <div class="recent-amount" :class="tx.transaction_type">
            {{ tx.transaction_type === 'income' ? '+' : '-' }}¥{{ tx.amount.toFixed(2) }}
          </div>
        </div>
      </div>
    </div>

    <!-- 消费趋势图 -->
    <div class="trend-section">
      <div class="section-header">
        <h2>📊 消费趋势</h2>
        <span class="trend-summary">近{{ trendDays }}天支出 ¥{{ trend.total_expense.toFixed(2) }} · 收入 ¥{{ trend.total_income.toFixed(2) }}</span>
      </div>
      <div class="trend-chart" v-if="trend.daily.length > 0">
        <div v-for="d in trend.daily" :key="d.date" class="bar-group">
          <div class="bar-expense" 
            :style="{ height: (d.expense / maxExpense * 100) + '%', opacity: d.expense > 0 ? 1 : 0.3 }"
            :title="`${d.date}: ¥${d.expense.toFixed(2)}`">
          </div>
          <div class="bar-income" 
            :style="{ height: (d.income / maxExpense * 100) + '%', opacity: d.income > 0 ? 1 : 0 }"
            :title="`${d.date}: ¥${d.income.toFixed(2)}`">
          </div>
        </div>
      </div>
      <div v-else class="empty-trend">暂无交易数据</div>
    </div>

    <!-- 消费分类 -->
    <div class="category-section" v-if="trend.categories.length > 0">
      <div class="section-header">
        <h2>🏷 消费分类</h2>
      </div>
      <div class="category-bars">
        <div v-for="cat in trend.categories" :key="cat.name" class="category-item">
          <span class="cat-icon">{{ getCategoryIcon(cat.name).icon }}</span>
          <span class="cat-name">{{ cat.name }}</span>
          <div class="cat-bar-bg">
            <div class="cat-bar-fill" :style="{ width: (cat.amount / totalCategoryAmount * 100) + '%', background: getCategoryIcon(cat.name).color }"></div>
          </div>
          <span class="cat-amount">¥{{ cat.amount.toFixed(2) }}</span>
          <span class="cat-percent">{{ (cat.amount / totalCategoryAmount * 100).toFixed(1) }}%</span>
        </div>
      </div>
    </div>

    <!-- 月度报表 -->
    <div class="monthly-section" v-if="monthly">
      <div class="section-header">
        <h2>📋 {{ monthly.year }}年{{ monthly.month }}月报表</h2>
      </div>
      <div class="monthly-grid">
        <div class="monthly-card">
          <div class="monthly-label">总收入</div>
          <div class="monthly-value income">¥{{ monthly.total_income.toFixed(2) }}</div>
        </div>
        <div class="monthly-card">
          <div class="monthly-label">总支出</div>
          <div class="monthly-value expense">¥{{ monthly.total_expense.toFixed(2) }}</div>
        </div>
        <div class="monthly-card">
          <div class="monthly-label">净收支</div>
          <div class="monthly-value" :class="monthly.net >= 0 ? 'income' : 'expense'">¥{{ monthly.net.toFixed(2) }}</div>
        </div>
        <div class="monthly-card">
          <div class="monthly-label">储蓄率</div>
          <div class="monthly-value">{{ monthly.savings_rate }}%</div>
        </div>
        <div class="monthly-card">
          <div class="monthly-label">日均支出</div>
          <div class="monthly-value">¥{{ monthly.daily_avg_expense.toFixed(2) }}</div>
        </div>
        <div class="monthly-card">
          <div class="monthly-label">交易笔数</div>
          <div class="monthly-value">{{ monthly.transaction_count }}</div>
        </div>
      </div>
      <!-- 周对比 -->
      <div class="weekly-comparison" v-if="monthly.weekly">
        <div class="weekly-header">📅 周对比</div>
        <div class="weekly-bars">
          <div v-for="w in monthly.weekly" :key="w.week" class="weekly-item">
            <span class="weekly-label">第{{ w.week }}周</span>
            <div class="weekly-bar-group">
              <div class="weekly-bar income" :style="{ width: Math.min(w.income / Math.max(...monthly.weekly.map(x => x.income), 1) * 100, 100) + '%' }"></div>
              <div class="weekly-bar expense" :style="{ width: Math.min(w.expense / Math.max(...monthly.weekly.map(x => x.expense), 1) * 100, 100) + '%' }"></div>
            </div>
            <span class="weekly-text">入¥{{ w.income.toFixed(0) }} 出¥{{ w.expense.toFixed(0) }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 功能特性 -->
    <div class="features">
      <div class="feature-card">
        <h3>🤖 全自动无感记账</h3>
        <p>银行通知自动解析，无需手动分类</p>
      </div>
      <div class="feature-card">
        <h3>🧠 多 Agent 协同</h3>
        <p>可配置多个 AI Agent，各自独立分析</p>
      </div>
      <div class="feature-card">
        <h3>🎨 深色主题</h3>
        <p>电影质感，安静克制</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { marked } from 'marked'
import { fetchDashboardStats, fetchLatestAnalysis, runAnalysis, fetchTrend, fetchMonthlyReport, fetchTransactions, fetchAssets, fetchLiabilities } from '~/utils/api'
import { getCategoryIcon, getAssetIcon, getLiabilityIcon } from '~/utils/icons'

const stats = ref({
  net_assets: 0,
  total_assets: 0,
  total_liabilities: 0,
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
  consumption: marked(analysis.value.consumption || ''),
  investment: marked(analysis.value.investment || ''),
  suggestion: marked(analysis.value.suggestion || '')
}))

const analyzing = ref(false)
const clientReady = ref(false)
const trend = ref({ daily: [], categories: [], total_expense: 0, total_income: 0 })
const monthly = ref(null)
const recentTransactions = ref([])
const assets = ref([])
const liabilities = ref([])

const maxExpense = computed(() => Math.max(...trend.value.daily.map(d => d.expense), 1))
const trendDays = computed(() => trend.value.daily.length)
const totalCategoryAmount = computed(() => trend.value.categories.reduce((s, c) => s + c.amount, 0) || 1)

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
  const names = { cmb: '招商银行', icbc: '工商银行', ccb: '建设银行', alipay: '支付宝', wechat_pay: '微信支付', cash: '现金', other: '其他' }
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

onMounted(() => {
  clientReady.value = true
  loadStats()
  loadAnalysis()
  loadTrend()
  loadMonthly()
  loadRecentTransactions()
  loadAssets()
})
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 2rem;
}

.hero {
  text-align: center;
  margin-bottom: 3rem;
}

.hero h1 {
  font-size: 2.5rem;
  color: var(--accent);
  margin-bottom: 0.5rem;
}

.tagline {
  font-size: 1.1rem;
  color: var(--text-secondary);
  font-style: italic;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
  margin-bottom: 3rem;
}

.stat-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  text-align: center;
  transition: all 0.2s;
}

.stat-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 20px rgba(180, 83, 9, 0.1);
}

.stat-label {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}

.stat-value {
  color: var(--text-primary);
  font-size: 1.8rem;
  font-weight: 600;
}

.stat-value.income {
  color: var(--success);
}

.stat-value.expense {
  color: var(--danger);
}

.ai-section {
  margin-bottom: 3rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.section-header h2 {
  color: var(--text-primary);
  font-size: 1.5rem;
}

.btn {
  padding: 0.5rem 1.5rem;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: var(--accent);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: var(--accent-hover);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.insights {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 1.5rem;
}

.insight-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.insight-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.insight-icon {
  font-size: 1.5rem;
}

.insight-title {
  color: var(--text-primary);
  font-weight: 600;
}

.insight-content {
  color: var(--text-secondary);
  line-height: 1.6;
}

.insight-content :deep(p) {
  margin: 0.5rem 0;
}

.insight-content :deep(ul),
.insight-content :deep(ol) {
  margin: 0.5rem 0;
  padding-left: 1.5rem;
}

.insight-content :deep(li) {
  margin: 0.25rem 0;
}

.insight-content :deep(strong) {
  color: var(--text-primary);
  font-weight: 600;
}

.insight-content :deep(code) {
  background: var(--bg-tertiary);
  padding: 0.1rem 0.3rem;
  border-radius: 4px;
  font-size: 0.9em;
}

.insight-content :deep(h1),
.insight-content :deep(h2),
.insight-content :deep(h3) {
  color: var(--text-primary);
  margin: 1rem 0 0.5rem;
}

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
}

/* 资产概览 */
.asset-section { margin-bottom: 3rem; }
.asset-summary { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1rem; }
.asset-bar-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.asset-bar-label { color: var(--text-secondary); font-size: 0.9rem; }
.asset-bar-value { font-size: 1.5rem; font-weight: 700; }
.asset-bar-value.income { color: var(--success); }
.asset-bar-value.expense { color: var(--danger); }
.asset-compare-bar { display: flex; height: 24px; border-radius: 12px; overflow: hidden; gap: 2px; }
.asset-fill { display: flex; align-items: center; justify-content: center; font-size: 0.75rem; color: white; font-weight: 500; transition: width 0.5s; min-width: 0; overflow: hidden; white-space: nowrap; }
.asset-green { background: var(--success); }
.asset-red { background: var(--danger); }
.asset-breakdown { display: flex; flex-direction: column; gap: 0.5rem; margin-bottom: 1rem; }
.asset-detail-item { display: flex; align-items: center; gap: 0.75rem; padding: 0.5rem 1rem; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 8px; }
.asset-detail-icon { font-size: 1.1rem; flex-shrink: 0; }
.asset-detail-name { color: var(--text-primary); font-size: 0.85rem; min-width: 50px; }
.asset-detail-bar-bg { flex: 1; height: 6px; background: var(--bg-tertiary, rgba(255,255,255,0.05)); border-radius: 3px; overflow: hidden; }
.asset-detail-bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.asset-detail-amount { color: var(--text-primary); font-size: 0.85rem; font-weight: 600; min-width: 70px; text-align: right; }
.asset-detail-count { color: var(--text-secondary); font-size: 0.75rem; min-width: 30px; }
.liability-mini { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 1rem; }
.liability-mini-title { color: var(--text-primary); font-weight: 600; margin-bottom: 0.8rem; font-size: 0.9rem; }
.liability-mini-item { display: flex; align-items: center; gap: 0.75rem; padding: 0.4rem 0; }
.liability-mini-icon { font-size: 1rem; flex-shrink: 0; }
.liability-mini-info { flex: 1; min-width: 0; }
.liability-mini-name { color: var(--text-primary); font-size: 0.85rem; margin-bottom: 0.2rem; }
.liability-mini-bar { height: 4px; background: var(--bg-tertiary, rgba(255,255,255,0.05)); border-radius: 2px; overflow: hidden; }
.liability-mini-fill { height: 100%; background: var(--success); border-radius: 2px; transition: width 0.3s; }
.liability-mini-amount { color: var(--text-primary); font-size: 0.85rem; font-weight: 600; min-width: 80px; text-align: right; }
.liability-mini-total { color: var(--text-secondary); font-weight: 400; }

/* 最近交易 */
.recent-section { margin-bottom: 3rem; }
.view-all { color: var(--accent); text-decoration: none; font-size: 0.9rem; font-weight: 500; }
.view-all:hover { text-decoration: underline; }
.recent-list { display: flex; flex-direction: column; gap: 0.5rem; }
.recent-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.8rem 1rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  transition: all 0.2s;
}
.recent-item:hover { border-color: var(--accent); }
.recent-icon {
  width: 36px; height: 36px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 1.1rem; flex-shrink: 0;
}
.recent-info { flex: 1; min-width: 0; }
.recent-desc {
  color: var(--text-primary); font-weight: 500; font-size: 0.95rem;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.recent-meta { display: flex; gap: 0.4rem; font-size: 0.8rem; color: var(--text-secondary); margin-top: 0.2rem; }
.recent-amount { font-size: 1.1rem; font-weight: 600; flex-shrink: 0; }
.recent-amount.income { color: var(--success); }
.recent-amount.expense { color: var(--danger); }

/* 趋势图 */
.trend-section { margin-bottom: 3rem; }
.trend-summary { color: var(--text-secondary); font-size: 0.9rem; }
.trend-chart {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 120px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1rem;
  overflow-x: auto;
}
.bar-group {
  display: flex;
  flex-direction: column-reverse;
  align-items: center;
  flex: 1;
  min-width: 8px;
  height: 100%;
  gap: 1px;
  position: relative;
}
.bar-expense {
  width: 100%;
  max-width: 12px;
  background: var(--danger);
  border-radius: 3px 3px 0 0;
  transition: all 0.2s;
  min-height: 2px;
}
.bar-income {
  width: 100%;
  max-width: 12px;
  background: var(--success);
  border-radius: 3px 3px 0 0;
  transition: all 0.2s;
  min-height: 0;
}
.bar-group:hover .bar-expense, .bar-group:hover .bar-income {
  filter: brightness(1.3);
}
.empty-trend { color: var(--text-secondary); text-align: center; padding: 3rem; }

/* 分类 */
.category-section { margin-bottom: 3rem; }
.category-bars { display: flex; flex-direction: column; gap: 0.6rem; }
.category-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.6rem 1rem;
}
.cat-icon { font-size: 1.2rem; flex-shrink: 0; }
.cat-name { color: var(--text-primary); font-size: 0.9rem; min-width: 70px; }
.cat-bar-bg {
  flex: 1;
  height: 8px;
  background: var(--bg-tertiary, rgba(255,255,255,0.05));
  border-radius: 4px;
  overflow: hidden;
}
.cat-bar-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.cat-amount { color: var(--text-primary); font-size: 0.85rem; font-weight: 600; min-width: 80px; text-align: right; }
.cat-percent { color: var(--text-secondary); font-size: 0.8rem; min-width: 50px; text-align: right; }

/* 月报 */
.monthly-section { margin-bottom: 3rem; }
.monthly-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.monthly-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem; text-align: center; }
.monthly-label { color: var(--text-secondary); font-size: 0.8rem; margin-bottom: 0.3rem; }
.monthly-value { color: var(--text-primary); font-size: 1.4rem; font-weight: 600; }
.monthly-value.income { color: var(--success); }
.monthly-value.expense { color: var(--danger); }
.weekly-comparison { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 10px; padding: 1.2rem; }
.weekly-header { color: var(--text-primary); font-weight: 600; margin-bottom: 0.8rem; }
.weekly-bars { display: flex; flex-direction: column; gap: 0.5rem; }
.weekly-item { display: flex; align-items: center; gap: 0.75rem; }
.weekly-label { color: var(--text-secondary); font-size: 0.85rem; min-width: 50px; }
.weekly-bar-group { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.weekly-bar { height: 6px; border-radius: 3px; min-width: 2px; transition: width 0.3s; }
.weekly-bar.income { background: var(--success); }
.weekly-bar.expense { background: var(--danger); }
.weekly-text { color: var(--text-secondary); font-size: 0.8rem; min-width: 120px; text-align: right; }

.feature-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 2rem;
  transition: all 0.2s;
}

.feature-card:hover {
  border-color: var(--accent);
  box-shadow: 0 0 20px rgba(180, 83, 9, 0.2);
}

.feature-card h3 {
  color: var(--text-primary);
  margin-bottom: 0.5rem;
}

.feature-card p {
  color: var(--text-secondary);
}
</style>

/* 响应式适配 */
@media (max-width: 768px) {
  .stats {
    grid-template-columns: repeat(2, 1fr);
  }
  .charts-row {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 480px) {
  .stats {
    grid-template-columns: 1fr;
  }
}

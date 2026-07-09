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

    <!-- AI 分析区域 -->
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
          <p class="insight-content">{{ analysis.consumption }}</p>
        </div>
        
        <div class="insight-card">
          <div class="insight-header">
            <span class="insight-icon">📈</span>
            <span class="insight-title">投资分析</span>
          </div>
          <p class="insight-content">{{ analysis.investment }}</p>
        </div>
        
        <div class="insight-card">
          <div class="insight-header">
            <span class="insight-icon">💡</span>
            <span class="insight-title">建议</span>
          </div>
          <p class="insight-content">{{ analysis.suggestion }}</p>
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
import { fetchDashboardStats, fetchLatestAnalysis, runAnalysis, fetchTrend, fetchMonthlyReport } from '~/utils/api'
import { getCategoryIcon } from '~/utils/icons'

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

const analyzing = ref(false)
const trend = ref({ daily: [], categories: [], total_expense: 0, total_income: 0 })
const monthly = ref(null)

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

onMounted(() => {
  loadStats()
  loadAnalysis()
  loadTrend()
  loadMonthly()
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
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
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

.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 2rem;
}

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

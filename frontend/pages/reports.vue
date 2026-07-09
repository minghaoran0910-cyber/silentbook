<template>
  <div class="container">
    <div class="header">
      <h1>📊 财务报表</h1>
      <div class="tab-bar">
        <button :class="{ active: activeTab === 'daily' }" @click="activeTab = 'daily'">日报</button>
        <button :class="{ active: activeTab === 'weekly' }" @click="activeTab = 'weekly'">周报</button>
        <button :class="{ active: activeTab === 'monthly' }" @click="activeTab = 'monthly'">月报</button>
        <button :class="{ active: activeTab === 'yearly' }" @click="activeTab = 'yearly'">年报</button>
      </div>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    
    <div v-else-if="error" class="error">{{ error }}</div>

    <!-- 日报 -->
    <div v-else-if="activeTab === 'daily'" class="report-section">
      <div class="report-header">
        <h2>{{ dailyReport.date }} 日报</h2>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">总收入</div>
          <div class="stat-value income">¥{{ dailyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">总支出</div>
          <div class="stat-value expense">¥{{ dailyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">净收入</div>
          <div class="stat-value" :class="dailyReport.net >= 0 ? 'income' : 'expense'">
            ¥{{ dailyReport.net?.toFixed(2) || '0.00' }}
          </div>
        </div>
        <div class="stat-card">
          <div class="stat-label">交易笔数</div>
          <div class="stat-value">{{ dailyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="dailyReport.categories?.length" class="category-list">
        <h3>支出分类</h3>
        <div v-for="cat in dailyReport.categories" :key="cat.name" class="category-item">
          <span class="category-name">{{ cat.name }}</span>
          <span class="category-amount">¥{{ cat.amount.toFixed(2) }}</span>
        </div>
      </div>
    </div>

    <!-- 周报 -->
    <div v-else-if="activeTab === 'weekly'" class="report-section">
      <div class="report-header">
        <h2>{{ weeklyReport.week_start }} ~ {{ weeklyReport.week_end }} 周报</h2>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">总收入</div>
          <div class="stat-value income">¥{{ weeklyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">总支出</div>
          <div class="stat-value expense">¥{{ weeklyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">日均支出</div>
          <div class="stat-value">¥{{ weeklyReport.daily_avg_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">交易笔数</div>
          <div class="stat-value">{{ weeklyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="weeklyReport.daily?.length" class="daily-breakdown">
        <h3>每日明细</h3>
        <div v-for="day in weeklyReport.daily" :key="day.date" class="daily-item">
          <span class="daily-date">{{ day.weekday }} ({{ day.date }})</span>
          <span class="daily-income" v-if="day.income > 0">+¥{{ day.income.toFixed(2) }}</span>
          <span class="daily-expense" v-if="day.expense > 0">-¥{{ day.expense.toFixed(2) }}</span>
          <span class="daily-count">{{ day.count }}笔</span>
        </div>
      </div>
    </div>

    <!-- 月报 -->
    <div v-else-if="activeTab === 'monthly'" class="report-section">
      <div class="report-header">
        <h2>{{ monthlyReport.year }}年{{ monthlyReport.month }}月 月报</h2>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">总收入</div>
          <div class="stat-value income">¥{{ monthlyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">总支出</div>
          <div class="stat-value expense">¥{{ monthlyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">储蓄率</div>
          <div class="stat-value">{{ monthlyReport.savings_rate?.toFixed(1) || '0.0' }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">交易笔数</div>
          <div class="stat-value">{{ monthlyReport.transaction_count || 0 }}</div>
        </div>
      </div>
      <div v-if="monthlyReport.expense_categories?.length" class="category-list">
        <h3>支出分类</h3>
        <div v-for="cat in monthlyReport.expense_categories" :key="cat.name" class="category-item">
          <span class="category-name">{{ cat.name }}</span>
          <div class="category-bar">
            <div class="category-bar-fill" :style="{ width: (cat.amount / monthlyReport.total_expense * 100) + '%' }"></div>
          </div>
          <span class="category-amount">¥{{ cat.amount.toFixed(2) }}</span>
          <span class="category-pct">{{ (cat.amount / monthlyReport.total_expense * 100).toFixed(1) }}%</span>
        </div>
      </div>
    </div>

    <!-- 年报 -->
    <div v-else-if="activeTab === 'yearly'" class="report-section">
      <div class="report-header">
        <h2>{{ yearlyReport.year }}年 年报</h2>
      </div>
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">总收入</div>
          <div class="stat-value income">¥{{ yearlyReport.total_income?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">总支出</div>
          <div class="stat-value expense">¥{{ yearlyReport.total_expense?.toFixed(2) || '0.00' }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">储蓄率</div>
          <div class="stat-value">{{ yearlyReport.savings_rate?.toFixed(1) || '0.0' }}%</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">月均支出</div>
          <div class="stat-value">¥{{ yearlyReport.monthly_avg_expense?.toFixed(2) || '0.00' }}</div>
        </div>
      </div>
      <div v-if="yearlyReport.monthly?.length" class="monthly-breakdown">
        <h3>月度趋势</h3>
        <div class="monthly-chart">
          <div v-for="month in yearlyReport.monthly" :key="month.month" class="month-bar">
            <div class="bar-container">
              <div class="bar-income" :style="{ height: getBarHeight(month.income, yearlyReport.max_monthly) + '%' }"></div>
              <div class="bar-expense" :style="{ height: getBarHeight(month.expense, yearlyReport.max_monthly) + '%' }"></div>
            </div>
            <div class="month-label">{{ month.month }}月</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'

const activeTab = ref('daily')
const loading = ref(false)
const error = ref('')

const dailyReport = ref({})
const weeklyReport = ref({})
const monthlyReport = ref({})
const yearlyReport = ref({})

const fetchReport = async (type) => {
  loading.value = true
  error.value = ''
  try {
    const config = useRuntimeConfig()
    const apiBase = config.public?.apiBase || 'http://localhost:8000'
    const resp = await fetch(`${apiBase}/stats/${type}`)
    if (!resp.ok) throw new Error('加载失败')
    const data = await resp.json()
    
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

const getBarHeight = (value, max) => {
  if (!max || max === 0) return 0
  return Math.min((value / max) * 100, 100)
}

watch(activeTab, (newTab) => {
  fetchReport(newTab)
})

onMounted(() => {
  fetchReport('daily')
})
</script>

<style scoped>
.container {
  max-width: 1000px;
  margin: 0 auto;
  padding: 2rem;
}

.header {
  margin-bottom: 2rem;
}

.header h1 {
  color: var(--accent);
  margin-bottom: 1rem;
}

.tab-bar {
  display: flex;
  gap: 0.5rem;
  border-bottom: 1px solid var(--border);
}

.tab-bar button {
  padding: 0.75rem 1.5rem;
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-bar button.active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

.loading, .error {
  text-align: center;
  padding: 2rem;
  color: var(--text-secondary);
}

.error {
  color: var(--danger);
}

.report-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.report-header h2 {
  color: var(--text-primary);
  margin-bottom: 1.5rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1rem;
  margin-bottom: 2rem;
}

.stat-card {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}

.stat-label {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}

.stat-value {
  font-size: 1.5rem;
  font-weight: 600;
  color: var(--text-primary);
}

.stat-value.income { color: var(--success); }
.stat-value.expense { color: var(--danger); }

.category-list, .daily-breakdown, .monthly-breakdown {
  margin-top: 1.5rem;
}

.category-list h3, .daily-breakdown h3, .monthly-breakdown h3 {
  color: var(--text-primary);
  margin-bottom: 1rem;
}

.category-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
}

.category-name {
  min-width: 80px;
  color: var(--text-primary);
}

.category-bar {
  flex: 1;
  height: 8px;
  background: var(--bg-primary);
  border-radius: 4px;
  overflow: hidden;
}

.category-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 4px;
}

.category-amount {
  color: var(--text-primary);
  font-weight: 500;
}

.category-pct {
  color: var(--text-secondary);
  font-size: 0.9rem;
  min-width: 50px;
  text-align: right;
}

.daily-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
}

.daily-date {
  min-width: 150px;
  color: var(--text-primary);
}

.daily-income {
  color: var(--success);
  font-weight: 500;
}

.daily-expense {
  color: var(--danger);
  font-weight: 500;
}

.daily-count {
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.monthly-chart {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
  height: 200px;
  padding: 1rem 0;
}

.month-bar {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
}

.bar-container {
  width: 100%;
  height: 150px;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  gap: 2px;
}

.bar-income {
  width: 100%;
  background: var(--success);
  border-radius: 2px 2px 0 0;
  min-height: 2px;
}

.bar-expense {
  width: 100%;
  background: var(--danger);
  border-radius: 0 0 2px 2px;
  min-height: 2px;
}

.month-label {
  color: var(--text-secondary);
  font-size: 0.8rem;
}
</style>

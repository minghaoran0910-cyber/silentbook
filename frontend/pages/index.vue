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
import { ref, onMounted } from 'vue'
import { fetchDashboardStats, fetchLatestAnalysis, runAnalysis } from '~/utils/api'

const stats = ref({
  net_assets: 0,
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

const loadStats = async () => {
  try {
    stats.value = await fetchDashboardStats()
  } catch (error) {
    console.error('加载统计失败:', error)
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

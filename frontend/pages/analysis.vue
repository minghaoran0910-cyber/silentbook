<template>
  <div class="container">
    <div class="header">
      <h1>AI 分析</h1>
      <button @click="analyze" class="btn btn-primary" :disabled="analyzing">
        {{ analyzing ? '分析中...' : '重新分析' }}
      </button>
    </div>

    <div v-if="analyzing" class="loading-state">
      <div class="spinner"></div>
      <p>AI 正在分析您的财务数据...</p>
    </div>

    <div v-else class="analysis-grid">
      <div class="analysis-card">
        <div class="card-header">
          <span class="card-icon">💸</span>
          <h2>消费分析</h2>
        </div>
        <p class="card-content">{{ analysis.consumption }}</p>
      </div>

      <div class="analysis-card">
        <div class="card-header">
          <span class="card-icon">📈</span>
          <h2>投资分析</h2>
        </div>
        <p class="card-content">{{ analysis.investment }}</p>
      </div>

      <div class="analysis-card">
        <div class="card-header">
          <span class="card-icon">💡</span>
          <h2>建议</h2>
        </div>
        <p class="card-content">{{ analysis.suggestion }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { runAnalysis, fetchLatestAnalysis } from '~/utils/api'

const analyzing = ref(false)
const analysis = ref({
  consumption: '暂无分析数据',
  investment: '暂无分析数据',
  suggestion: '暂无分析数据'
})

const analyze = async () => {
  analyzing.value = true
  try {
    analysis.value = await runAnalysis()
  } catch (error) {
    console.error('分析失败:', error)
  } finally {
    analyzing.value = false
  }
}

onMounted(async () => {
  try {
    const data = await fetchLatestAnalysis()
    if (data.consumption && data.consumption !== '暂无分析') {
      analysis.value = data
    }
  } catch (e) {
    console.error('加载分析失败:', e)
  }
})
</script>

<style scoped>
.container {
  max-width: 1200px;
  margin: 0 auto;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.header h1 {
  font-size: 1.8rem;
  color: var(--text-primary);
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

.loading-state {
  text-align: center;
  padding: 4rem;
  color: var(--text-secondary);
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 1rem;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.analysis-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1.5rem;
}

.analysis-card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.card-icon {
  font-size: 1.5rem;
}

.card-header h2 {
  font-size: 1.2rem;
  color: var(--text-primary);
}

.card-content {
  color: var(--text-secondary);
  line-height: 1.7;
}
</style>

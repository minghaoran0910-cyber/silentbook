<template>
  <div class="container">
    <h1>设置</h1>

    <div class="settings-section">
      <h2>通知源</h2>
      <p class="section-desc">配置要解析的银行/支付平台通知</p>
      
      <div class="source-list">
        <div v-for="source in sources" :key="source.id" class="source-item">
          <div class="source-info">
            <span class="source-icon">{{ source.icon }}</span>
            <span class="source-name">{{ source.name }}</span>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="source.enabled" @change="saveSource(source)">
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
    </div>

    <div class="settings-section">
      <h2>AI Agent</h2>
      <p class="section-desc">配置分析用的 AI Agent</p>
      
      <div class="mode-selector">
        <div class="setting-row">
          <span>分析模式</span>
          <select v-model="agentMode" class="select" @change="saveAgentMode">
            <option value="auto">自动（优先 OpenClaw）</option>
            <option value="openclaw">OpenClaw（三 Agent）</option>
            <option value="local">本地 LLM</option>
          </select>
        </div>
      </div>
      
      <div class="agent-list">
        <div v-for="agent in agents" :key="agent.id" class="agent-item">
          <div class="agent-info">
            <span class="agent-icon">{{ agent.icon }}</span>
            <div>
              <span class="agent-name">{{ agent.name }}</span>
              <span class="agent-desc">{{ agent.description }}</span>
            </div>
          </div>
          <label class="toggle">
            <input type="checkbox" v-model="agent.enabled" @change="saveAgent(agent)">
            <span class="toggle-slider"></span>
          </label>
        </div>
      </div>
    </div>

    <div class="settings-section">
      <h2>系统</h2>
      
      <div class="setting-row">
        <span>API 地址</span>
        <input type="text" v-model="apiBase" class="input" placeholder="http://localhost:8000">
      </div>
      
      <div class="setting-row">
        <span>自动分析</span>
        <label class="toggle">
          <input type="checkbox" v-model="autoAnalyze">
          <span class="toggle-slider"></span>
        </label>
      </div>
    </div>

    <div class="settings-section">
      <h2>数据管理</h2>
      <p class="section-desc">导入导出数据</p>
      
      <div class="data-actions">
        <button @click="exportData" class="btn-action">
          <span>📥</span> 导出 CSV
        </button>
        <label class="btn-action import-btn">
          <span>📤</span> 导入 CSV
          <input type="file" accept=".csv" @change="importData" style="display: none">
        </label>
      </div>
      
      <div v-if="importResult" class="import-result" :class="importResult.success ? 'success' : 'error'">
        {{ importResult.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated } from 'vue'
import { getSources, updateSources, getAgentConfigs, updateAgentConfig } from '~/utils/api'

const sources = ref([
  { id: 'cmb', name: '招商银行', icon: '🏦', enabled: true },
  { id: 'icbc', name: '工商银行', icon: '🏦', enabled: true },
  { id: 'ccb', name: '建设银行', icon: '🏦', enabled: true },
  { id: 'alipay', name: '支付宝', icon: '💳', enabled: true },
  { id: 'wechat_pay', name: '微信支付', icon: '💳', enabled: true }
])

const agents = ref([
  { id: 1, name: '墨砚', icon: '📊', description: '财务总监 - 消费分析', enabled: true },
  { id: 2, name: '远瞻', icon: '📈', description: '投资总监 - 投资分析', enabled: true },
  { id: 3, name: '老油条', icon: '🍵', description: '综合建议 - 财务规划', enabled: true }
])

const agentMode = ref('auto')
const apiBase = ref('/api')
const autoAnalyze = ref(false)
const importResult = ref(null)

const exportData = async () => {
  try {
    const response = await fetch(`${apiBase.value}/export/csv`)
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `silentbook_export_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    window.URL.revokeObjectURL(url)
    importResult.value = { success: true, message: '导出成功' }
  } catch (e) {
    importResult.value = { success: false, message: '导出失败: ' + e.message }
  }
}

const importData = async (event) => {
  const file = event.target.files[0]
  if (!file) return
  
  const reader = new FileReader()
  reader.onload = async (e) => {
    const content = e.target.result
    try {
      const response = await fetch(`${apiBase.value}/import/csv`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      })
      const result = await response.json()
      importResult.value = { success: true, message: `导入成功: ${result.imported} 条记录` }
    } catch (err) {
      importResult.value = { success: false, message: '导入失败: ' + err.message }
    }
  }
  reader.readAsText(file)
}

const saveAgentMode = async () => {
  try {
    await $fetch(`${apiBase.value}/settings`, {
      method: 'PUT',
      body: { agent_mode: agentMode.value }
    })
  } catch (e) {
    console.error('保存分析模式失败:', e)
  }
}

const saveSource = async (source) => {
  const map = {}
  sources.value.forEach(s => { map[s.id] = s.enabled })
  await updateSources(map)
}

const saveAgent = async (agent) => {
  await updateAgentConfig(agent.id, { is_active: agent.enabled })
}

const loadAll = async () => {
  try {
    const srcMap = await getSources()
    sources.value.forEach(s => { s.enabled = srcMap[s.id] !== false })
    
    const agentList = await getAgentConfigs()
    if (agentList.length > 0) {
      agents.value = agentList.map(a => ({
        id: a.id, name: a.name, description: a.system_prompt || 'AI Agent', enabled: a.is_active
      }))
    }
  } catch (e) {
    console.error('加载设置失败:', e)
  }
  
  try {
    const config = useRuntimeConfig()
    apiBase.value = config.public?.apiBase || ''
  } catch {
    apiBase.value = ''
  }
}
onMounted(loadAll)
onActivated(loadAll)
</script>

<style scoped>
.container {
  max-width: 800px;
  margin: 0 auto;
}

h1 {
  font-size: 1.8rem;
  color: var(--text-primary);
  margin-bottom: 2rem;
}

.settings-section {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}

.settings-section h2 {
  font-size: 1.2rem;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
}

.section-desc {
  color: var(--text-secondary);
  font-size: 0.9rem;
  margin-bottom: 1.5rem;
}

.source-list, .agent-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.source-item, .agent-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem;
  border-radius: 8px;
  background: var(--bg-primary);
}

.source-info, .agent-info {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.source-icon {
  font-size: 1.3rem;
}

.source-name, .agent-name {
  color: var(--text-primary);
  font-weight: 500;
}

.agent-desc {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-left: 0.5rem;
}

.toggle {
  position: relative;
  display: inline-block;
  width: 44px;
  height: 24px;
}

.toggle input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: var(--bg-tertiary, #333);
  border-radius: 24px;
  transition: 0.2s;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background: white;
  border-radius: 50%;
  transition: 0.2s;
}

.toggle input:checked + .toggle-slider {
  background: var(--accent);
}

.toggle input:checked + .toggle-slider:before {
  transform: translateX(20px);
}

.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
}

.setting-row:last-child {
  border-bottom: none;
}

.setting-row span {
  color: var(--text-primary);
}

.input {
  padding: 0.5rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  width: 240px;
}

.input:focus {
  outline: none;
  border-color: var(--accent);
}

.select {
  padding: 0.5rem 0.75rem;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-primary);
  cursor: pointer;
}

.select:focus {
  outline: none;
  border-color: var(--accent);
}

.agent-icon {
  font-size: 1.3rem;
}

.mode-selector {
  margin-bottom: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--border);
}

/* 数据管理 */
.data-actions {
  display: flex;
  gap: 1rem;
  margin-top: 1rem;
}

.btn-action {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1.5rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.2s;
}

.btn-action:hover {
  border-color: var(--accent);
  background: var(--bg-tertiary);
}

.import-btn {
  position: relative;
}

.import-result {
  margin-top: 1rem;
  padding: 0.75rem;
  border-radius: 8px;
  font-size: 0.9rem;
}

.import-result.success {
  background: rgba(34, 197, 94, 0.1);
  color: var(--success);
  border: 1px solid var(--success);
}

.import-result.error {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
  border: 1px solid var(--danger);
}
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

<template>
  <div class="container">
    <h1>设置</h1>

    <div class="settings-section">
      <h2>通知源</h2>
      <p class="section-desc">配置要解析的银行/支付平台通知</p>
      
      <div class="source-list">
        <div v-for="source in sources" :key="source.id" class="source-item">
          <div class="source-info">
            <AppIcon :icon="source.icon" :size="20" class="source-icon" />
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
      
      <!-- 用户自定义 AI 配置 -->
      <div class="ai-config-section">
        <h3>自定义模型配置</h3>
        <p class="config-desc">填写你自己的 API 参数，分析时将使用此模型</p>
        
        <div class="config-form">
          <div class="form-row">
            <label>API Base URL</label>
            <input type="text" v-model="aiConfig.api_base" class="input full-width" 
                   placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1">
          </div>
          <div class="form-row">
            <label>API Key</label>
            <div class="input-with-action">
              <input :type="showApiKey ? 'text' : 'password'" v-model="aiConfig.api_key" class="input full-width" 
                     :placeholder="aiConfig.api_key_masked || 'sk-...'">
              <button @click="showApiKey = !showApiKey" class="btn-icon" title="显示/隐藏" :aria-label="showApiKey ? '隐藏' : '显示'">
                <AppIcon :icon="showApiKey ? 'EyeSlash' : 'Eye'" :size="16" />
              </button>
            </div>
          </div>
          <div class="form-row">
            <label>模型名称</label>
            <input type="text" v-model="aiConfig.model_name" class="input full-width" 
                   placeholder="qwen-plus / gpt-4o-mini / glm-4-flash">
          </div>
          <div class="form-actions">
            <button @click="saveAiConfig" class="btn-primary" :disabled="savingAiConfig">
              <AppIcon v-if="!savingAiConfig" icon="FloppyDisk" :size="15" />
              {{ savingAiConfig ? '保存中...' : '保存配置' }}
            </button>
            <button @click="testAiConfig" class="btn-secondary" :disabled="testingAiConfig">
              <AppIcon v-if="!testingAiConfig" icon="PlugsConnected" :size="15" />
              {{ testingAiConfig ? '测试中...' : '测试连接' }}
            </button>
          </div>
          <div v-if="aiConfigMessage" class="config-message" :class="aiConfigMessageType">
            {{ aiConfigMessage }}
          </div>
        </div>
      </div>
      
      <!-- OpenClaw 绑定 -->
      <div class="openclaw-bindding-section">
        <h3>OpenClaw 绑定</h3>
        <p class="config-desc">绑定后分析结果可推送到对应的 OpenClaw Agent</p>
        
        <div v-if="openclawBinding.bound" class="binding-status bound">
          <span class="bound-label"><AppIcon icon="Check" :size="15" /> 已绑定: {{ openclawBinding.agent_label }} ({{ openclawBinding.agent_id }})</span>
          <button @click="unbindOpenClaw" class="btn-small btn-danger">解除绑定</button>
        </div>
        <div v-else>
          <div class="form-actions">
            <button @click="fetchOpenClawAgents" class="btn-secondary" :disabled="fetchingAgents">
              <AppIcon v-if="!fetchingAgents" icon="MagnifyingGlass" :size="15" />
              {{ fetchingAgents ? '获取中...' : '获取 Agent 清单' }}
            </button>
          </div>
          <div v-if="openclawAgents.length > 0" class="agent-select-list">
            <div v-for="a in openclawAgents" :key="a.id" class="agent-select-item" @click="bindOpenClaw(a)">
              <span>{{ a.label || a.id }}</span>
              <span class="agent-id">{{ a.id }}</span>
            </div>
          </div>
          <div v-if="openclawFetchError" class="config-message error">{{ openclawFetchError }}</div>
        </div>
      </div>
      
      <div class="agent-list">
        <div v-for="agent in agents" :key="agent.id" class="agent-item">
          <div class="agent-info">
            <AppIcon :icon="agent.icon" :size="20" class="agent-icon" />
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
        <span class="readonly-value">{{ effectiveApiBase }}</span>
      </div>
      <p class="section-desc">由部署配置（NUXT_PUBLIC_API_BASE）决定，修改请改环境变量后重启前端。</p>
    </div>

    <div class="settings-section">
      <h2>账户安全</h2>
      <p class="section-desc">修改登录密码（需验证旧密码，成功后请重新登录）</p>

      <div class="form-grid">
        <div class="form-group">
          <label>旧密码</label>
          <div class="password-field">
            <input v-model="pwdForm.oldPassword" :type="showPwd.old ? 'text' : 'password'" placeholder="输入旧密码" autocomplete="current-password" />
            <button type="button" class="icon-btn" @click="showPwd.old = !showPwd.old" :aria-label="showPwd.old ? '隐藏' : '显示'">
              <AppIcon :icon="showPwd.old ? 'EyeSlash' : 'Eye'" :size="16" />
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>新密码（至少 6 位）</label>
          <div class="password-field">
            <input v-model="pwdForm.newPassword" :type="showPwd.new ? 'text' : 'password'" placeholder="输入新密码" autocomplete="new-password" />
            <button type="button" class="icon-btn" @click="showPwd.new = !showPwd.new" :aria-label="showPwd.new ? '隐藏' : '显示'">
              <AppIcon :icon="showPwd.new ? 'EyeSlash' : 'Eye'" :size="16" />
            </button>
          </div>
        </div>
        <div class="form-group">
          <label>确认新密码</label>
          <input v-model="pwdForm.confirmPassword" type="password" placeholder="再次输入新密码" autocomplete="new-password" />
        </div>
      </div>
      <div class="form-actions">
        <button @click="handleChangePassword" class="btn-primary" :disabled="changingPwd">
          {{ changingPwd ? '修改中...' : '修改密码' }}
        </button>
      </div>
      <div v-if="pwdMessage" class="config-message" :class="pwdMessageType">{{ pwdMessage }}</div>
    </div>

    <div class="settings-section">
      <h2>数据管理</h2>
      <p class="section-desc">导入导出数据</p>
      
      <div class="data-actions">
        <button @click="exportData" class="btn-action">
          <AppIcon icon="DownloadSimple" :size="17" /> 导出 CSV
        </button>
        <label class="btn-action import-btn">
          <AppIcon icon="UploadSimple" :size="17" /> 导入 CSV
          <input type="file" accept=".csv" @change="importData" style="display: none">
        </label>
        <label class="btn-action import-btn">
          <AppIcon icon="FileText" :size="17" /> 导入 PDF 流水
          <input type="file" accept=".pdf" @change="importPdf" style="display: none">
        </label>
      </div>
      <p class="pdf-hint">支持招商银行标准格式 PDF 流水</p>
      
      <div v-if="importResult" class="import-result" :class="importResult.success ? 'success' : 'error'">
        {{ importResult.message }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onActivated } from 'vue'
import { getSources, updateSources, getAgentConfigs, updateAgentConfig, fetchAiConfig, updateAiConfig, testAiConfigConnection, fetchOpenClawAgents as fetchOpenClawAgentsApi, fetchOpenClawBinding, bindOpenClawAgent, unbindOpenClawAgent, updateSettings as updateSettingsApi, getApiBaseUrl, downloadExportCsv, importCsvContent, importPdfFile, changePassword as changePasswordApi, clearAuth } from '~/utils/api'

const sources = ref([
  { id: 'cmb', name: '招商银行', icon: 'Bank', enabled: true },
  { id: 'icbc', name: '工商银行', icon: 'Bank', enabled: true },
  { id: 'ccb', name: '建设银行', icon: 'Bank', enabled: true },
  { id: 'alipay', name: '支付宝', icon: 'Wallet', enabled: true },
  { id: 'wechat_pay', name: '微信支付', icon: 'DeviceMobile', enabled: true }
])

const agents = ref([
  { id: 1, name: '墨砚', icon: 'ChartLine', description: '财务总监 - 消费分析', enabled: true },
  { id: 2, name: '远瞻', icon: 'TrendUp', description: '投资总监 - 投资分析', enabled: true },
  { id: 3, name: '老油条', icon: 'BookOpen', description: '综合建议 - 财务规划', enabled: true }
])

const agentMode = ref('auto')
// 当前生效的后端地址（只读展示，由部署配置决定，不可在此修改）
const effectiveApiBase = ref('/api')
const importResult = ref(null)

// 修改密码
const pwdForm = ref({ oldPassword: '', newPassword: '', confirmPassword: '' })
const showPwd = ref({ old: false, new: false })
const changingPwd = ref(false)
const pwdMessage = ref('')
const pwdMessageType = ref('')

const handleChangePassword = async () => {
  pwdMessage.value = ''
  if (!pwdForm.value.oldPassword || !pwdForm.value.newPassword) {
    pwdMessage.value = '请填写旧密码和新密码'
    pwdMessageType.value = 'error'
    return
  }
  if (pwdForm.value.newPassword.length < 6) {
    pwdMessage.value = '新密码至少 6 位'
    pwdMessageType.value = 'error'
    return
  }
  if (pwdForm.value.newPassword !== pwdForm.value.confirmPassword) {
    pwdMessage.value = '两次输入的新密码不一致'
    pwdMessageType.value = 'error'
    return
  }
  changingPwd.value = true
  try {
    await changePasswordApi(pwdForm.value.oldPassword, pwdForm.value.newPassword)
    pwdMessage.value = '密码修改成功，正在跳转重新登录…'
    pwdMessageType.value = 'success'
    pwdForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
    setTimeout(() => {
      clearAuth()
      navigateTo('/auth')
    }, 1200)
  } catch (e) {
    pwdMessage.value = '修改失败: ' + (e.message || '未知错误')
    pwdMessageType.value = 'error'
  } finally {
    changingPwd.value = false
  }
}

// AI 配置
const aiConfig = ref({ api_base: '', api_key: '', api_key_masked: '', model_name: '' })
const showApiKey = ref(false)
const savingAiConfig = ref(false)
const testingAiConfig = ref(false)
const aiConfigMessage = ref('')
const aiConfigMessageType = ref('')

const exportData = async () => {
  try {
    // 经统一出口：带鉴权 Cookie 下载
    const blob = await downloadExportCsv()
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
      const result = await importCsvContent(content)
      importResult.value = { success: true, message: `导入成功: ${result.imported} 条记录` }
    } catch (err) {
      importResult.value = { success: false, message: '导入失败: ' + err.message }
    }
  }
  reader.readAsText(file)
}

const importPdf = async (event) => {
  const file = event.target.files[0]
  if (!file) return

  importResult.value = { success: true, message: '正在解析 PDF...' }

  try {
    const result = await importPdfFile(file)

    if (result.status === 'ok') {
      importResult.value = { success: true, message: `${result.bank} | 成功导入 ${result.imported} 条记录` }
    } else if (result.status === 'warning') {
      importResult.value = { success: false, message: `${result.message}` }
    } else {
      importResult.value = { success: false, message: `❌ ${result.detail || '导入失败'}` }
    }
  } catch (err) {
    importResult.value = { success: false, message: 'PDF 导入失败: ' + err.message }
  }
}

const saveAgentMode = async () => {
  try {
    await updateSettingsApi({ agent_mode: agentMode.value })
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

const saveAiConfig = async () => {
  savingAiConfig.value = true
  aiConfigMessage.value = ''
  try {
    const resp = await updateAiConfig({
      api_base: aiConfig.value.api_base,
      api_key: aiConfig.value.api_key || undefined,
      model_name: aiConfig.value.model_name
    })
    aiConfigMessage.value = '配置已保存'
    aiConfigMessageType.value = 'success'
    if (resp.api_key_masked) aiConfig.value.api_key_masked = resp.api_key_masked
    aiConfig.value.api_key = ''  // 清空输入框
  } catch (e) {
    aiConfigMessage.value = '❌ 保存失败: ' + (e.message || e)
    aiConfigMessageType.value = 'error'
  } finally {
    savingAiConfig.value = false
    setTimeout(() => { aiConfigMessage.value = '' }, 5000)
  }
}

const testAiConfig = async () => {
  testingAiConfig.value = true
  aiConfigMessage.value = ''
  try {
    const resp = await testAiConfigConnection()
    if (resp.status === 'ok') {
      aiConfigMessage.value = resp.message
      aiConfigMessageType.value = 'success'
    } else {
      aiConfigMessage.value = '❌ ' + resp.message
      aiConfigMessageType.value = 'error'
    }
  } catch (e) {
    aiConfigMessage.value = '❌ 测试失败: ' + (e.message || e)
    aiConfigMessageType.value = 'error'
  } finally {
    testingAiConfig.value = false
    setTimeout(() => { aiConfigMessage.value = '' }, 8000)
  }
}

const loadAiConfig = async () => {
  try {
    const resp = await fetchAiConfig()
    aiConfig.value = { ...resp, api_key: '' }
  } catch (e) {
    console.error('加载 AI 配置失败:', e)
  }
}

// OpenClaw 绑定
const openclawBinding = ref({ bound: false, agent_id: '', agent_label: '' })
const openclawAgents = ref([])
const fetchingAgents = ref(false)
const openclawFetchError = ref('')

const fetchOpenClawAgents = async () => {
  fetchingAgents.value = true
  openclawFetchError.value = ''
  openclawAgents.value = []
  try {
    const resp = await fetchOpenClawAgentsApi()
    if (resp.status === 'ok') {
      openclawAgents.value = resp.agents || []
      if (openclawAgents.value.length === 0) {
        openclawFetchError.value = 'Gateway 没有返回可用 Agent'
      }
    } else {
      openclawFetchError.value = resp.message || '获取失败'
    }
  } catch (e) {
    openclawFetchError.value = '连接失败: ' + (e.message || e)
  } finally {
    fetchingAgents.value = false
  }
}

const bindOpenClaw = async (agent) => {
  try {
    const resp = await bindOpenClawAgent(agent.id, agent.label || agent.id)
    openclawBinding.value = resp
    openclawAgents.value = []
  } catch (e) {
    openclawFetchError.value = '绑定失败: ' + (e.message || e)
  }
}

const unbindOpenClaw = async () => {
  try {
    await unbindOpenClawAgent()
    openclawBinding.value = { bound: false, agent_id: '', agent_label: '' }
  } catch (e) {
    console.error('解除绑定失败:', e)
  }
}

const loadOpenClawBinding = async () => {
  try {
    const resp = await fetchOpenClawBinding()
    openclawBinding.value = resp
  } catch (e) {
    console.error('加载 OpenClaw 绑定失败:', e)
  }
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
    effectiveApiBase.value = getApiBaseUrl() || ''
  } catch {
    effectiveApiBase.value = ''
  }
  
  // 加载 AI 配置
  await loadAiConfig()
  // 加载 OpenClaw 绑定
  await loadOpenClawBinding()
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
  display: inline-flex;
  color: var(--accent);
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

.readonly-value {
  color: var(--text-secondary);
  font-family: monospace;
  font-size: 0.85rem;
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
  display: inline-flex;
  color: var(--accent);
}

.mode-selector {
  margin-bottom: 1rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--border);
}

/* 账户安全表单 */
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin: 1rem 0;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-group label {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--text-secondary);
}

.form-group input {
  padding: 0.55rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 0.9rem;
  width: 100%;
}

.form-group input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.password-field {
  position: relative;
  display: flex;
  align-items: center;
}

.password-field input {
  padding-right: 2.5rem;
}

.password-field .icon-btn {
  position: absolute;
  right: 0.4rem;
  width: 30px;
  height: 30px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  cursor: pointer;
}

.password-field .icon-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
}

@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
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

/* AI 配置区域 */
.ai-config-section {
  margin: 1rem 0;
  padding: 1rem;
  background: var(--bg-primary);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.ai-config-section h3 {
  font-size: 1rem;
  margin-bottom: 0.25rem;
}

.config-desc {
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-bottom: 1rem;
}

.config-form .form-row {
  margin-bottom: 0.75rem;
}

.config-form label {
  display: block;
  color: var(--text-secondary);
  font-size: 0.85rem;
  margin-bottom: 0.25rem;
}

.input.full-width {
  width: 100%;
}

.input-with-action {
  display: flex;
  gap: 0.5rem;
}

.input-with-action .input {
  flex: 1;
}

.btn-icon {
  padding: 0.5rem;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
}

.form-actions {
  display: flex;
  gap: 0.75rem;
  margin-top: 1rem;
}

.btn-primary {
  padding: 0.6rem 1.2rem;
  background: var(--accent);
  color: var(--accent-ink);
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  padding: 0.6rem 1.2rem;
  background: var(--bg-secondary);
  color: var(--text-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
}

.btn-secondary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.config-message {
  margin-top: 0.75rem;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  font-size: 0.9rem;
}

.config-message.success {
  background: rgba(34, 197, 94, 0.1);
  color: var(--success);
}

.config-message.error {
  background: rgba(239, 68, 68, 0.1);
  color: var(--danger);
}

/* OpenClaw 绑定 */
.openclaw-bindding-section {
  margin: 1rem 0;
  padding: 1rem;
  background: var(--bg-primary);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.openclaw-bindding-section h3 {
  font-size: 1rem;
  margin-bottom: 0.25rem;
}

.binding-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem;
  border-radius: 8px;
  margin-top: 0.5rem;
}

.binding-status.bound {
  background: rgba(34, 197, 94, 0.1);
  border: 1px solid rgba(34, 197, 94, 0.3);
}

.bound-label {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: var(--success);
  font-weight: 500;
}

.btn-small {
  padding: 0.3rem 0.75rem;
  font-size: 0.85rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  cursor: pointer;
  background: var(--bg-secondary);
  color: var(--text-primary);
}

.btn-danger {
  color: var(--danger);
  border-color: var(--danger);
}

.agent-select-list {
  margin-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.agent-select-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
}

.agent-select-item:hover {
  border-color: var(--accent);
  background: var(--bg-tertiary);
}

.agent-id {
  color: var(--text-secondary);
  font-size: 0.8rem;
  font-family: monospace;
}

.pdf-hint {
  color: var(--text-secondary);
  font-size: 0.8rem;
  margin-top: 0.5rem;
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

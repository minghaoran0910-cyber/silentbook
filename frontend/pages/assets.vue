<template>
  <div class="container">
    <div class="header">
      <h1>资产管理</h1>
      <button @click="showAddForm = !showAddForm" class="btn btn-primary">
        {{ showAddForm ? '取消' : '+ 添加资产' }}
      </button>
    </div>

    <!-- 总览卡片 -->
    <div class="overview">
      <div class="overview-card">
        <div class="label">总资产</div>
        <div class="value income">¥{{ totalAssets.toFixed(2) }}</div>
      </div>
      <div class="overview-card">
        <div class="label">总负债</div>
        <div class="value expense">¥{{ totalLiabilities.toFixed(2) }}</div>
      </div>
      <div class="overview-card highlight">
        <div class="label">净资产</div>
        <div class="value">¥{{ (totalAssets - totalLiabilities).toFixed(2) }}</div>
      </div>
    </div>

    <!-- 添加资产表单 -->
    <div v-if="showAddForm" class="form-card">
      <h3>{{ editingId ? '编辑资产' : '添加资产' }}</h3>
      <form @submit.prevent="handleSubmit">
        <div class="form-grid">
          <div class="form-group">
            <label>名称</label>
            <input v-model="form.name" type="text" required placeholder="如：招商银行储蓄卡" />
          </div>
          <div class="form-group">
            <label>类型</label>
            <select v-model="form.asset_type" required>
              <option value="cash">现金</option>
              <option value="savings">存款</option>
              <option value="fund">基金</option>
              <option value="stock">股票</option>
              <option value="bond">债券</option>
              <option value="property">房产</option>
              <option value="other">其他</option>
            </select>
          </div>
          <div class="form-group">
            <label>所属机构</label>
            <input v-model="form.account" type="text" placeholder="如：招商银行" />
          </div>
          <div class="form-group">
            <label>当前价值</label>
            <input v-model="form.current_value" type="number" step="0.01" required placeholder="0.00" />
          </div>
          <div class="form-group">
            <label>初始投入</label>
            <input v-model="form.initial_value" type="number" step="0.01" placeholder="0.00" />
          </div>
          <div class="form-group">
            <label>流动性</label>
            <select v-model="form.liquidity">
              <option value="high">高（随时可取）</option>
              <option value="medium">中</option>
              <option value="low">低（锁定期）</option>
            </select>
          </div>
          <div class="form-group full">
            <label>备注</label>
            <input v-model="form.notes" type="text" placeholder="可选" />
          </div>
        </div>
        <div class="form-actions">
          <button type="submit" class="btn btn-primary">{{ editingId ? '更新' : '添加' }}</button>
          <button type="button" @click="resetForm" class="btn btn-secondary">清空</button>
        </div>
      </form>
    </div>

    <!-- 资产列表 -->
    <div class="section">
      <h2>📊 资产列表</h2>
      <div v-if="assets.length === 0" class="empty">暂无资产，点击右上角添加</div>
      <div v-else class="asset-list">
        <div v-for="asset in assets" :key="asset.id" class="asset-card">
          <div class="asset-icon" :style="{ background: getAssetIcon(asset.asset_type).color + '20' }">
            <span class="icon-emoji">{{ getAssetIcon(asset.asset_type).icon }}</span>
          </div>
          <div class="asset-info">
            <div class="asset-name">{{ asset.name }}</div>
            <div class="asset-meta">
              <span class="tag">{{ getAssetIcon(asset.asset_type).label }}</span>
              <span v-if="asset.account" class="tag">{{ asset.account }}</span>
              <span class="tag" :class="`tag-${asset.liquidity}`">{{ liquidityLabels[asset.liquidity] || asset.liquidity }}</span>
            </div>
          </div>
          <div class="asset-value">
            <div class="amount">¥{{ asset.current_value.toFixed(2) }}</div>
            <div v-if="asset.initial_value > 0" class="initial">投入: ¥{{ asset.initial_value.toFixed(2) }}</div>
            <div v-if="asset.initial_value > 0" class="profit" :class="{ positive: asset.current_value >= asset.initial_value, negative: asset.current_value < asset.initial_value }">
              {{ asset.current_value >= asset.initial_value ? '+' : '' }}¥{{ (asset.current_value - asset.initial_value).toFixed(2) }}
            </div>
          </div>
          <div class="asset-actions">
            <button @click="editAsset(asset)" class="btn-icon" title="编辑">✏</button>
            <button @click="removeAsset(asset.id)" class="btn-icon danger" title="删除">🗑</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 负债列表 -->
    <div class="section">
      <div class="section-header">
        <h2>💳 负债列表</h2>
        <button @click="showAddLiabilityForm = !showAddLiabilityForm" class="btn btn-small">
          {{ showAddLiabilityForm ? '取消' : '+ 添加负债' }}
        </button>
      </div>
      
      <div v-if="showAddLiabilityForm" class="form-card">
        <form @submit.prevent="handleLiabilitySubmit">
          <div class="form-grid">
            <div class="form-group">
              <label>名称</label>
              <input v-model="liabilityForm.name" type="text" required placeholder="如：京东白条" />
            </div>
            <div class="form-group">
              <label>类型</label>
              <select v-model="liabilityForm.liability_type" required>
                <option value="credit_card">信用卡</option>
                <option value="loan">贷款</option>
                <option value="mortgage">房贷</option>
                <option value="other">其他</option>
              </select>
            </div>
            <div class="form-group">
              <label>总额</label>
              <input v-model="liabilityForm.total_amount" type="number" step="0.01" required placeholder="0.00" />
            </div>
            <div class="form-group">
              <label>当前待还</label>
              <input v-model="liabilityForm.current_amount" type="number" step="0.01" required placeholder="0.00" />
            </div>
            <div class="form-group">
              <label>年利率(%)</label>
              <input v-model="liabilityForm.interest_rate" type="number" step="0.01" placeholder="0" />
            </div>
            <div class="form-group">
              <label>到期日</label>
              <input v-model="liabilityForm.due_date" type="date" />
            </div>
          </div>
          <div class="form-actions">
            <button type="submit" class="btn btn-primary">添加</button>
          </div>
        </form>
      </div>

      <div v-if="liabilities.length === 0" class="empty">暂无负债</div>
      <div v-else class="liability-list">
        <div v-for="liab in liabilities" :key="liab.id" class="liability-card">
          <div class="asset-icon" :style="{ background: getLiabilityIcon(liab.liability_type).color + '20' }">
            <span class="icon-emoji">{{ getLiabilityIcon(liab.liability_type).icon }}</span>
          </div>
          <div class="asset-info">
            <div class="asset-name">{{ liab.name }}</div>
            <div class="asset-meta">
              <span class="tag">{{ getLiabilityIcon(liab.liability_type).label }}</span>
              <span v-if="liab.interest_rate > 0" class="tag">利率: {{ liab.interest_rate }}%</span>
              <span v-if="liab.due_date" class="tag">到期: {{ liab.due_date }}</span>
            </div>
            <div class="repay-progress" v-if="liab.total_amount > 0">
              <div class="repay-bar-bg">
                <div class="repay-bar-fill" :style="{ width: ((liab.total_amount - liab.current_amount) / liab.total_amount * 100) + '%' }"></div>
              </div>
              <span class="repay-text">已还 ¥{{ (liab.total_amount - liab.current_amount).toFixed(2) }} / ¥{{ liab.total_amount.toFixed(2) }} ({{ ((liab.total_amount - liab.current_amount) / liab.total_amount * 100).toFixed(1) }}%)</span>
            </div>
          </div>
          <div class="asset-value">
            <div class="amount expense">¥{{ liab.current_amount.toFixed(2) }}</div>
            <div class="initial">总额: ¥{{ liab.total_amount.toFixed(2) }}</div>
          </div>
          <div class="asset-actions">
            <button @click="removeLiability(liab.id)" class="btn-icon danger" title="删除">🗑</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { fetchAssets, createAsset, updateAsset, deleteAsset, fetchLiabilities, createLiability, deleteLiability } from '~/utils/api'
import { assetTypeIcons, liabilityTypeIcons, liquidityLabels, statusLabels, getAssetIcon, getLiabilityIcon } from '~/utils/icons'

const assets = ref([])
const liabilities = ref([])
const showAddForm = ref(false)
const showAddLiabilityForm = ref(false)
const editingId = ref(null)

const form = ref({
  name: '', asset_type: 'savings', account: '', current_value: 0, initial_value: 0, liquidity: 'medium', notes: ''
})

const liabilityForm = ref({
  name: '', liability_type: 'credit_card', total_amount: 0, current_amount: 0, interest_rate: 0, due_date: ''
})

const totalAssets = computed(() => assets.value.filter(a => a.status === 'active').reduce((s, a) => s + a.current_value, 0))
const totalLiabilities = computed(() => liabilities.value.filter(l => l.status === 'active').reduce((s, l) => s + l.current_amount, 0))

// 按类型分组的资产
const assetsByType = computed(() => {
  const groups = {}
  assets.value.filter(a => a.status === 'active').forEach(a => {
    if (!groups[a.asset_type]) groups[a.asset_type] = []
    groups[a.asset_type].push(a)
  })
  return groups
})

const loadData = async () => {
  try {
    const [a, l] = await Promise.all([fetchAssets(), fetchLiabilities()])
    assets.value = a
    liabilities.value = l
  } catch (e) { console.error(e) }
}

const handleSubmit = async () => {
  try {
    if (editingId.value) {
      await updateAsset(editingId.value, form.value)
    } else {
      await createAsset(form.value)
    }
    resetForm()
    await loadData()
  } catch (e) { console.error(e) }
}

const editAsset = (asset) => {
  editingId.value = asset.id
  form.value = { ...asset }
  showAddForm.value = true
}

const removeAsset = async (id) => {
  if (!confirm('确认删除？')) return
  await deleteAsset(id)
  await loadData()
}

const resetForm = () => {
  editingId.value = null
  form.value = { name: '', asset_type: 'savings', account: '', current_value: 0, initial_value: 0, liquidity: 'medium', notes: '' }
}

const handleLiabilitySubmit = async () => {
  try {
    await createLiability(liabilityForm.value)
    liabilityForm.value = { name: '', liability_type: 'credit_card', total_amount: 0, current_amount: 0, interest_rate: 0, due_date: '' }
    showAddLiabilityForm.value = false
    await loadData()
  } catch (e) { console.error(e) }
}

const removeLiability = async (id) => {
  if (!confirm('确认删除？')) return
  await deleteLiability(id)
  await loadData()
}

onMounted(loadData)
</script>

<style scoped>
.container { max-width: 1200px; margin: 0 auto; padding: 2rem; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
.header h1 { color: var(--accent); }
.overview { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
.overview-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; text-align: center; }
.overview-card.highlight { border-color: var(--accent); box-shadow: 0 0 20px rgba(180,83,9,0.1); }
.overview-card .label { color: var(--text-secondary); font-size: 0.9rem; margin-bottom: 0.5rem; }
.overview-card .value { font-size: 1.8rem; font-weight: 600; }
.overview-card .value.income { color: var(--success); }
.overview-card .value.expense { color: var(--danger); }
.form-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 2rem; }
.form-card h3 { color: var(--text-primary); margin-bottom: 1rem; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1rem; }
.form-group { display: flex; flex-direction: column; }
.form-group.full { grid-column: 1 / -1; }
.form-group label { color: var(--text-secondary); font-size: 0.85rem; margin-bottom: 0.3rem; }
.form-group input, .form-group select { background: var(--bg-tertiary); border: 1px solid var(--border); border-radius: 8px; padding: 0.6rem; color: var(--text-primary); }
.form-group input:focus, .form-group select:focus { outline: none; border-color: var(--accent); }
.form-actions { display: flex; gap: 0.5rem; margin-top: 1rem; }
.section { margin-bottom: 2rem; }
.section h2 { color: var(--text-primary); margin-bottom: 1rem; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
.empty { color: var(--text-secondary); text-align: center; padding: 2rem; }
.asset-list, .liability-list { display: flex; flex-direction: column; gap: 0.75rem; }
.asset-card, .liability-card { background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.5rem; display: flex; align-items: center; gap: 1rem; justify-content: space-between; }
.asset-card:hover, .liability-card:hover { border-color: var(--accent); }
.asset-icon { width: 48px; height: 48px; border-radius: 12px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.icon-emoji { font-size: 1.5rem; }
.asset-info { flex: 1; }
.asset-name { color: var(--text-primary); font-weight: 600; }
.asset-meta { display: flex; gap: 0.5rem; margin-top: 0.3rem; }
.tag { background: var(--bg-tertiary); color: var(--text-secondary); padding: 0.1rem 0.5rem; border-radius: 4px; font-size: 0.75rem; }
.asset-value { text-align: right; }
.amount { color: var(--text-primary); font-size: 1.2rem; font-weight: 600; }
.amount.expense { color: var(--danger); }
.initial { color: var(--text-secondary); font-size: 0.8rem; }
.profit { font-size: 0.85rem; font-weight: 600; }
.profit.positive { color: var(--success); }
.profit.negative { color: var(--danger); }
.asset-actions { display: flex; gap: 0.5rem; margin-left: 1rem; }
.btn-icon { background: transparent; border: none; color: var(--text-secondary); cursor: pointer; font-size: 1.1rem; padding: 0.25rem 0.5rem; border-radius: 6px; }
.btn-icon:hover { background: var(--bg-tertiary); }
.btn-icon.danger:hover { color: var(--danger); }
.btn { padding: 0.5rem 1.5rem; border: none; border-radius: 8px; cursor: pointer; font-weight: 500; }
.btn-primary { background: var(--accent); color: white; }
.btn-primary:hover { background: var(--accent-hover); }
.btn-secondary { background: var(--bg-tertiary); color: var(--text-secondary); }
.btn-small { padding: 0.3rem 0.8rem; font-size: 0.85rem; background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border); border-radius: 8px; cursor: pointer; }

/* 还款进度 */
.repay-progress { margin-top: 0.5rem; }
.repay-bar-bg { height: 6px; background: var(--bg-tertiary, rgba(255,255,255,0.05)); border-radius: 3px; overflow: hidden; }
.repay-bar-fill { height: 100%; background: var(--success); border-radius: 3px; transition: width 0.3s; }
.repay-text { color: var(--text-secondary); font-size: 0.75rem; margin-top: 0.2rem; display: block; }
</style>

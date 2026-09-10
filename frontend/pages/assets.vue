<template>
  <div class="mx-auto min-w-0 w-full max-w-5xl px-4 py-6">
    <!-- 页头：标题 + 右上角 ghost 同步 + 时间小字 -->
    <div class="flex flex-wrap items-center gap-3">
      <div class="mr-auto min-w-0">
        <h1 class="sb-h text-xl font-semibold" style="color: var(--text-primary)">资产管理</h1>
        <p class="mt-0.5 text-sm" style="color: var(--text-secondary)">家底多少，还欠多少，一眼看清。</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span v-if="lastSyncInfo" class="text-xs tabular-nums" style="color: var(--text-secondary)">上次同步：{{ lastSyncInfo }}</span>
        <UButton variant="ghost" color="neutral" :loading="syncing" :disabled="syncing" @click="syncAssets">
          <AppIcon v-if="!syncing" icon="ArrowClockwise" :size="15" />
          {{ syncing ? '同步中...' : '同步持仓' }}
        </UButton>
        <UButton @click="toggleAddForm">
          <AppIcon :icon="showAddForm ? 'X' : 'Plus'" :size="15" />
          {{ showAddForm ? '取消' : '添加资产' }}
        </UButton>
      </div>
    </div>
    <div v-if="goldPrice" class="mt-1 text-right text-xs tabular-nums" style="color: var(--text-secondary)">金价 ¥{{ goldPrice }}/克</div>

    <!-- 同步状态（替代原 .sync-result 色块） -->
    <UAlert
      v-if="syncResult"
      :color="syncResult.error ? 'error' : 'success'"
      variant="soft"
      :title="syncResult.message"
      :description="(syncResult.updated ? `更新 ${syncResult.updated} 个` : '') + (syncResult.failed ? ` 失败 ${syncResult.failed} 个` : '')"
      class="mt-4"
      close
      @update:open="syncResult = null"
    />

    <!-- 操作失败提示（替代 alert） -->
    <UAlert v-if="actionError" color="error" variant="soft" :title="actionError" class="mt-4" close @update:open="actionError = ''" />

    <!-- 加载中：骨架 -->
    <div v-if="loading" class="mt-4 space-y-4">
      <div class="grid grid-cols-1 gap-3 min-[480px]:grid-cols-3">
        <USkeleton v-for="i in 3" :key="i" class="h-[92px] w-full" />
      </div>
      <UCard class="sb-surface" :ui="{ body: 'p-5' }">
        <USkeleton class="h-5 w-40" />
        <USkeleton class="mt-3 h-44 w-full" />
      </UCard>
    </div>

    <!-- 加载失败 -->
    <UAlert
      v-else-if="loadError"
      class="mt-4"
      color="error"
      variant="soft"
      :title="loadError"
      :actions="[{ label: '重试', color: 'error', variant: 'solid', onClick: loadData }]"
    />

    <template v-else>
      <!-- ① 顶部家底卡：净资产大数字 + 三行 + 占比条（首页同款） -->
      <UCard class="sb-surface mt-4" " :ui="{ body: 'p-5' }">
        <div class="text-sm" style="color: var(--text-secondary)">净资产</div>
        <div class="sb-display mt-1 text-5xl font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ netWorth.toFixed(2) }}</div>
        <div class="mt-3 flex flex-col gap-1 text-sm tabular-nums">
          <div class="flex items-center justify-between gap-2">
            <span style="color: var(--text-secondary)">总资产</span>
            <span class="font-medium" style="color: var(--success)">¥{{ totalAssets.toFixed(2) }}</span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <span style="color: var(--text-secondary)">总负债</span>
            <span class="font-medium" style="color: var(--danger)">¥{{ totalLiabilities.toFixed(2) }}</span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <span style="color: var(--text-secondary)">净值</span>
            <span class="font-medium" style="color: var(--text-primary)">¥{{ netWorth.toFixed(2) }}</span>
          </div>
        </div>
        <div
          v-if="totalAssets > 0 || totalLiabilities > 0"
          class="mt-4 flex h-6 w-full gap-0.5 overflow-hidden motion-reduce:transition-none"
          style="border-radius: var(--radius-md)"
          role="img"
          aria-label="资产与负债占比"
        >
          <div
            class="flex h-full items-center justify-center overflow-hidden text-xs font-medium whitespace-nowrap"
            style="background: var(--success); color: var(--fill-ink)"
            :style="{ width: (assetShare) + '%' }"
          >
            <span v-if="totalAssets > 0" class="px-2 tabular-nums">资产 ¥{{ totalAssets.toFixed(0) }}</span>
          </div>
          <div
            class="flex h-full items-center justify-center overflow-hidden text-xs font-medium whitespace-nowrap"
            style="background: var(--danger); color: var(--fill-ink)"
            :style="{ width: (100 - assetShare) + '%' }"
          >
            <span v-if="totalLiabilities > 0" class="px-2 tabular-nums">负债 ¥{{ totalLiabilities.toFixed(0) }}</span>
          </div>
        </div>
      </UCard>

      <!-- 资产分类饼图 + 资产收益 -->
      <div v-if="assets.length > 0" class="mt-4 grid grid-cols-1 gap-3 min-[480px]:grid-cols-2">
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="sb-h mb-3 text-base font-semibold" style="color: var(--text-primary)">资产分类</h3>
          <div class="flex flex-wrap items-center gap-4">
            <div ref="assetPieEl" class="h-[180px] w-[180px] shrink-0" role="img" aria-label="资产分类分布图" />
            <div class="flex min-w-0 flex-1 flex-col gap-1.5">
              <div v-for="(item, i) in pieData" :key="item.type" class="flex items-center gap-1.5 text-sm">
                <span class="h-2.5 w-2.5 shrink-0 rounded-[3px]" :style="{ background: pieColors[i % pieColors.length] }" />
                <span class="min-w-10" style="color: var(--text-primary)">{{ item.label }}</span>
                <span class="tabular-nums" style="color: var(--text-secondary)">¥{{ item.value.toFixed(0) }}</span>
                <span class="text-xs tabular-nums" style="color: var(--text-secondary)">{{ item.pct }}%</span>
              </div>
            </div>
          </div>
        </UCard>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="sb-h mb-3 text-base font-semibold" style="color: var(--text-primary)">资产收益</h3>
          <div class="flex flex-col gap-2.5">
            <div v-for="item in pieData" :key="'p-' + item.type" class="flex items-center gap-2">
              <span class="min-w-12 text-sm" style="color: var(--text-primary)">{{ item.label }}</span>
              <UProgress :model-value="Math.min(Number(item.pct), 100)" :max="100" :color="item.profit >= 0 ? 'success' : 'error'" class="flex-1" />
              <span
                class="min-w-15 text-right text-sm font-semibold tabular-nums"
                :style="{ color: item.profit >= 0 ? 'var(--success)' : 'var(--danger)' }"
              >
                {{ item.profit >= 0 ? '+' : '' }}{{ item.profitRate }}%
              </span>
            </div>
          </div>
        </UCard>
      </div>

      <!-- 资产变化曲线（真实历史，非模拟） -->
      <UCard v-if="assets.length > 0" class="sb-surface mt-4" " :ui="{ body: 'p-5' }">
        <h3 class="sb-h mb-3 text-base font-semibold" style="color: var(--text-primary)">资产变化趋势</h3>
        <div ref="assetCurveEl" class="h-60 w-full" role="img" aria-label="资产变化趋势图" />
      </UCard>

      <!-- ② 资产列表：按类型分组折叠，组头显示组内合计 -->
      <div class="mt-8">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="sb-h text-lg font-semibold" style="color: var(--text-primary)">资产列表</h2>
          <UButton size="sm" variant="outline" color="neutral" @click="toggleAddForm">
            {{ showAddForm ? '取消' : '+ 添加资产' }}
          </UButton>
        </div>

        <!-- 筛选栏 -->
        <div class="mb-3 grid grid-cols-1 gap-2 min-[480px]:grid-cols-3">
          <UInput v-model="assetSearch" type="text" placeholder="搜索名称/机构..." class="w-full min-w-0" />
          <USelect v-model="assetTypeFilter" :items="assetTypeFilterItems" value-key="value" class="w-full min-w-0" />
          <USelect v-model="assetStatusFilter" :items="assetStatusFilterItems" value-key="value" class="w-full min-w-0" />
        </div>

        <UCard
          v-if="filteredAssets.length === 0"
          class="sb-surface text-center"
          :ui="{ body: 'p-8' }"
        >
          <p class="text-sm" style="color: var(--text-secondary)">{{ assets.length === 0 ? '暂无资产，点击右上角添加' : '没有匹配的资产' }}</p>
        </UCard>
        <div v-else class="flex flex-col gap-3">
          <UCard class="sb-surface"
            v-for="group in groupedAssets"
            :key="group.type"
            :ui="{ body: 'p-0' }"
          >
            <button
              type="button"
              class="flex w-full items-center gap-2 px-4 py-3 text-left motion-reduce:transition-none"
              :aria-expanded="!isGroupCollapsed(group.type)"
              :aria-label="group.label + '分组，合计' + group.total.toFixed(2)"
              @click="toggleGroup(group.type)"
            >
              <span class="min-w-0 flex-1 truncate text-sm font-semibold" style="color: var(--text-primary)">{{ group.label }}（{{ group.items.length }}）</span>
              <span class="shrink-0 text-sm font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ group.total.toFixed(2) }}</span>
              <AppIcon :icon="isGroupCollapsed(group.type) ? 'CaretDown' : 'CaretUp'" :size="14" />
            </button>
            <div v-show="!isGroupCollapsed(group.type)" class="flex flex-col gap-3 px-4 pb-4">
              <UCard class="sb-surface"
                v-for="asset in group.items"
                :key="asset.id"
                :ui="{ body: 'p-4' }"
              >
                <div class="flex items-center gap-3">
                  <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" :style="{ background: getAssetIcon(asset.asset_type).color + '20' }">
                    <AppIcon :icon="getAssetIcon(asset.asset_type).icon" :color="getAssetIcon(asset.asset_type).color" :size="20" />
                  </div>
                  <div class="min-w-0 flex-1">
                    <div class="truncate font-semibold" style="color: var(--text-primary)">{{ asset.name }}</div>
                    <div class="mt-1 flex flex-wrap gap-1.5">
                      <UBadge variant="soft" color="neutral">{{ getAssetIcon(asset.asset_type).label }}</UBadge>
                      <UBadge v-if="asset.account" variant="soft" color="neutral">{{ asset.account }}</UBadge>
                      <UBadge variant="soft" color="neutral">{{ liquidityLabels[asset.liquidity] || asset.liquidity }}</UBadge>
                    </div>
                  </div>
                  <div class="shrink-0 text-right">
                    <div class="text-lg font-semibold tabular-nums" style="color: var(--text-primary)">¥{{ asset.current_value.toFixed(2) }}</div>
                    <div v-if="asset.initial_value > 0" class="text-xs tabular-nums" style="color: var(--text-secondary)">投入: ¥{{ asset.initial_value.toFixed(2) }}</div>
                    <div
                      v-if="asset.initial_value > 0"
                      class="text-sm font-semibold tabular-nums"
                      :style="{ color: asset.current_value >= asset.initial_value ? 'var(--success)' : 'var(--danger)' }"
                    >
                      {{ asset.current_value >= asset.initial_value ? '+' : '' }}¥{{ (asset.current_value - asset.initial_value).toFixed(2) }}
                    </div>
                  </div>
                  <div class="flex shrink-0 gap-1">
                    <UButton size="xs" variant="ghost" color="neutral" title="编辑" aria-label="编辑资产" @click="editAsset(asset)">
                      <AppIcon icon="PencilSimple" :size="16" />
                    </UButton>
                    <UButton size="xs" variant="ghost" color="error" title="删除" aria-label="删除资产" @click="requestDeleteAsset(asset)">
                      <AppIcon icon="Trash" :size="16" />
                    </UButton>
                  </div>
                </div>
              </UCard>
            </div>
          </UCard>
        </div>
      </div>

      <!-- ③ 负债列表：剩余/总额进度 + 月供小字 -->
      <div class="mt-8">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h2 class="sb-h text-lg font-semibold" style="color: var(--text-primary)">负债列表</h2>
          <UButton size="sm" variant="outline" color="neutral" @click="showAddLiabilityForm = !showAddLiabilityForm">
            {{ showAddLiabilityForm ? '取消' : '+ 添加负债' }}
          </UButton>
        </div>

        <UCard
          v-if="liabilities.length === 0"
          class="sb-surface text-center"
          :ui="{ body: 'p-8' }"
        >
          <p class="text-sm" style="color: var(--text-secondary)">暂无负债</p>
        </UCard>
        <div v-else class="flex flex-col gap-3">
          <UCard class="sb-surface"
            v-for="liab in liabilities"
            :key="liab.id"
            :ui="{ body: 'p-4' }"
          >
            <div class="flex items-center gap-3">
              <div class="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl" :style="{ background: getLiabilityIcon(liab.liability_type).color + '20' }">
                <AppIcon :icon="getLiabilityIcon(liab.liability_type).icon" :color="getLiabilityIcon(liab.liability_type).color" :size="20" />
              </div>
              <div class="min-w-0 flex-1">
                <div class="truncate font-semibold" style="color: var(--text-primary)">{{ liab.name }}</div>
                <div class="mt-1 flex flex-wrap gap-1.5">
                  <UBadge variant="soft" color="neutral">{{ getLiabilityIcon(liab.liability_type).label }}</UBadge>
                  <UBadge v-if="liab.interest_rate > 0" variant="soft" color="neutral" class="tabular-nums">利率: {{ liab.interest_rate }}%</UBadge>
                  <UBadge v-if="liab.due_date" variant="soft" color="neutral" class="tabular-nums">到期: {{ liab.due_date }}</UBadge>
                </div>
                <div v-if="liab.total_amount > 0" class="mt-2">
                  <UProgress :model-value="liab.total_amount > 0 ? (liab.current_amount / liab.total_amount * 100) : 0" :max="100" color="error" />
                  <span class="mt-1 block text-xs tabular-nums" style="color: var(--text-secondary)">待还 ¥{{ liab.current_amount.toFixed(2) }} / ¥{{ liab.total_amount.toFixed(2) }} ({{ (liab.current_amount / liab.total_amount * 100).toFixed(1) }}%)</span>
                </div>
              </div>
              <div class="shrink-0 text-right">
                <div class="text-lg font-semibold tabular-nums" style="color: var(--danger)">¥{{ liab.current_amount.toFixed(2) }}</div>
                <div class="text-xs tabular-nums" style="color: var(--text-secondary)">总额: ¥{{ liab.total_amount.toFixed(2) }}</div>
                <div v-if="liab.min_payment > 0" class="mt-0.5 text-xs tabular-nums" style="color: var(--text-secondary)">月供 ¥{{ Number(liab.min_payment).toFixed(2) }}</div>
                <div v-else-if="liab.interest_rate > 0" class="mt-0.5 text-xs tabular-nums" style="color: var(--text-secondary)">年利率 {{ liab.interest_rate }}%</div>
              </div>
              <div class="flex shrink-0 gap-1">
                <UButton size="xs" variant="ghost" color="neutral" title="编辑" aria-label="编辑负债" @click="editLiability(liab)">
                  <AppIcon icon="PencilSimple" :size="16" />
                </UButton>
                <UButton size="xs" variant="ghost" color="error" title="删除" aria-label="删除负债" @click="requestDeleteLiability(liab)">
                  <AppIcon icon="Trash" :size="16" />
                </UButton>
              </div>
            </div>
          </UCard>
        </div>
      </div>
    </template>

    <!-- 添加/编辑资产弹窗 -->
    <UModal v-model:open="showAddForm" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-lg' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="sb-h mb-4 text-base font-semibold" style="color: var(--text-primary)">{{ editingId ? '编辑资产' : '添加资产' }}</h3>
          <form @submit.prevent="handleSubmit">
            <div class="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2">
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-name">名称</label>
                <UInput id="asset-name" v-model="form.name" type="text" required placeholder="如：招商银行储蓄卡" class="w-full min-w-0" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">类型</label>
                <USelect v-model="form.asset_type" :items="assetTypeItems" value-key="value" class="w-full min-w-0" />
                <NuxtLink to="/investments" class="mt-1 block text-xs motion-reduce:transition-none" style="color: var(--text-secondary)">股票/基金/债券/黄金请去投资页添加 →</NuxtLink>
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-account">所属机构</label>
                <UInput id="asset-account" v-model="form.account" type="text" placeholder="如：招商银行" class="w-full min-w-0" />
              </div>
              <!-- 黄金专属字段 -->
              <template v-if="form.asset_type === 'gold'">
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">实时金价</label>
                  <div class="rounded-md px-3 py-2 text-center text-sm font-semibold tabular-nums" style="background: var(--bg-tertiary); color: var(--text-primary)">
                    <span v-if="goldPriceState === 'ok' && goldPrice" class="inline-flex items-center gap-1.5"><AppIcon icon="Coins" :size="15" /> {{ goldPrice }} 元/克</span>
                    <span v-else-if="goldPriceState === 'error'" class="inline-flex items-center gap-1.5">
                      金价暂不可用，可手动填克价
                      <UButton size="xs" variant="ghost" @click="fetchGoldPrice">重试</UButton>
                    </span>
                    <span v-else>加载中...</span>
                  </div>
                </div>
                <div v-if="goldPriceState === 'error'" class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-gold-manual">手动克价（金价服务不可用时）</label>
                  <UInput id="asset-gold-manual" v-model="goldManualPrice" type="number" step="0.01" placeholder="如 1028.50" class="w-full min-w-0 tabular-nums" @input="calcGoldValue" />
                </div>
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-gold-grams">克数</label>
                  <UInput id="asset-gold-grams" v-model="form.goldGrams" type="number" step="0.0001" placeholder="0.00" class="w-full min-w-0 tabular-nums" @input="calcGoldValue" />
                </div>
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-gold-cost">成本克价</label>
                  <UInput id="asset-gold-cost" v-model="form.goldCostPerGram" type="number" step="0.01" placeholder="0.00" class="w-full min-w-0 tabular-nums" @input="calcGoldValue" />
                </div>
              </template>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-current">
                  {{ form.asset_type === 'cash' || form.asset_type === 'savings' ? '金额' : '当前价值' }} <span v-if="form.asset_type === 'gold'" class="text-xs font-normal">(自动计算)</span>
                </label>
                <UInput id="asset-current" v-model="form.current_value" type="number" step="0.01" required placeholder="0.00" :disabled="form.asset_type === 'gold' && form.goldGrams > 0" class="w-full min-w-0 tabular-nums" />
              </div>
              <div v-if="form.asset_type !== 'cash' && form.asset_type !== 'savings'" class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-initial">
                  初始投入 <span v-if="form.asset_type === 'gold'" class="text-xs font-normal">(自动计算)</span>
                </label>
                <UInput id="asset-initial" v-model="form.initial_value" type="number" step="0.01" placeholder="0.00" :disabled="form.asset_type === 'gold' && form.goldGrams > 0" class="w-full min-w-0 tabular-nums" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">流动性</label>
                <USelect v-model="form.liquidity" :items="liquidityItems" value-key="value" class="w-full min-w-0" />
              </div>
              <div class="min-w-0 min-[480px]:col-span-2">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="asset-notes">备注</label>
                <UInput id="asset-notes" v-model="form.notes" type="text" placeholder="可选" class="w-full min-w-0" />
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <UButton type="submit">{{ editingId ? '更新' : '添加' }}</UButton>
              <UButton type="button" variant="outline" color="neutral" @click="resetForm">清空</UButton>
              <UButton type="button" variant="ghost" color="neutral" @click="showAddForm = false">取消</UButton>
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- 添加/编辑负债弹窗 -->
    <UModal v-model:open="showAddLiabilityForm" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-lg' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="sb-h mb-4 text-base font-semibold" style="color: var(--text-primary)">{{ editingLiabilityId ? '编辑负债' : '添加负债' }}</h3>
          <form @submit.prevent="handleLiabilitySubmit">
            <div class="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2">
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-name">名称</label>
                <UInput id="liab-name" v-model="liabilityForm.name" type="text" required placeholder="如：京东白条" class="w-full min-w-0" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">类型</label>
                <USelect v-model="liabilityForm.liability_type" :items="liabilityTypeItems" value-key="value" class="w-full min-w-0" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-total">总额</label>
                <UInput id="liab-total" v-model="liabilityForm.total_amount" type="number" step="0.01" required placeholder="0.00" class="w-full min-w-0 tabular-nums" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-current">当前待还</label>
                <UInput id="liab-current" v-model="liabilityForm.current_amount" type="number" step="0.01" required placeholder="0.00" class="w-full min-w-0 tabular-nums" />
              </div>
              <!-- 信用卡专属字段 -->
              <template v-if="liabilityForm.liability_type === 'credit_card'">
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-min">本期应还</label>
                  <UInput id="liab-min" v-model="liabilityForm.min_payment" type="number" step="0.01" placeholder="0.00" class="w-full min-w-0 tabular-nums" />
                </div>
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">发卡银行</label>
                  <USelect v-model="selectedBank" :items="bankItems" value-key="value" class="w-full min-w-0" @update:model-value="onBankChange" />
                </div>
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)">账单日</label>
                  <USelect v-model="liabilityForm.billing_day" :items="billingDayItems" value-key="value" class="w-full min-w-0" @update:model-value="onBillingDayChange" />
                </div>
                <div class="min-w-0">
                  <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-due-cc">还款日</label>
                  <UInput id="liab-due-cc" v-model="liabilityForm.due_date" type="date" class="w-full min-w-0 tabular-nums" />
                  <small class="mt-1 block text-xs" style="color: var(--text-secondary)">账单日后 {{ repaymentDaysOffset }} 天</small>
                </div>
              </template>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-rate">年利率(%)</label>
                <UInput id="liab-rate" v-model="liabilityForm.interest_rate" type="number" step="0.01" placeholder="0" class="w-full min-w-0 tabular-nums" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" style="color: var(--text-secondary)" for="liab-due">到期日</label>
                <UInput id="liab-due" v-model="liabilityForm.due_date" type="date" class="w-full min-w-0 tabular-nums" />
              </div>
            </div>
            <div class="mt-4 flex flex-wrap gap-2">
              <UButton type="submit">{{ editingLiabilityId ? '保存' : '添加' }}</UButton>
              <UButton type="button" variant="outline" color="neutral" @click="cancelLiabilityEdit">取消</UButton>
            </div>
          </form>
        </UCard>
      </template>
    </UModal>

    <!-- 删除确认（替代 confirm） -->
    <UModal v-model:open="deleteConfirmOpen" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }">
      <template #content>
        <UCard class="sb-surface" :ui="{ body: 'p-5' }">
          <h3 class="sb-h text-base font-semibold" style="color: var(--text-primary)">删除{{ pendingDelete?.kind === 'liability' ? '负债' : '资产' }}</h3>
          <p class="mt-1 text-sm tabular-nums" style="color: var(--text-secondary)">确定删除「{{ pendingDelete?.name }}」<span v-if="pendingDelete?.amount">（¥{{ pendingDelete.amount }}）</span>？删除后无法恢复，此操作不可撤销。</p>
          <div class="mt-4 flex flex-wrap justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="pendingDelete = null">取消</UButton>
            <UButton color="error" @click="confirmDelete">确认删除</UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onActivated, computed, watch } from 'vue'
import { fetchAssets, createAsset, updateAsset, deleteAsset, fetchLiabilities, createLiability, updateLiability, deleteLiability, triggerAssetSync, fetchSyncStatus, fetchAssetCurve } from '~/utils/api'
import { useECharts } from '~/composables/useECharts'
import { assetTypeIcons, liabilityTypeIcons, liquidityLabels, statusLabels, getAssetIcon, getLiabilityIcon } from '~/utils/icons'

const assets = ref([])
const assetSearch = ref('')
const assetTypeFilter = ref('')
const assetStatusFilter = ref('')

const filteredAssets = computed(() => {
  return assets.value.filter(a => {
    if (assetSearch.value) {
      const search = assetSearch.value.toLowerCase()
      if (!a.name.toLowerCase().includes(search) &&
          !(a.account && a.account.toLowerCase().includes(search))) {
        return false
      }
    }
    if (assetTypeFilter.value && a.asset_type !== assetTypeFilter.value) return false
    if (assetStatusFilter.value && a.status !== assetStatusFilter.value) return false
    return true
  })
})
const liabilities = ref([])
const showAddForm = ref(false)
const showAddLiabilityForm = ref(false)
const editingId = ref(null)
const actionError = ref('')

// 筛选条件客户端持久化（SSR 安全：只在客户端读写 localStorage）
const FILTERS_KEY = 'sb-assets-filters'
const restoreFilters = () => {
  if (!import.meta.client) return
  try {
    const raw = JSON.parse(localStorage.getItem(FILTERS_KEY) || '{}')
    if (typeof raw.assetSearch === 'string') assetSearch.value = raw.assetSearch
    if (typeof raw.assetTypeFilter === 'string') assetTypeFilter.value = raw.assetTypeFilter
    if (typeof raw.assetStatusFilter === 'string') assetStatusFilter.value = raw.assetStatusFilter
  } catch {}
}
watch([assetSearch, assetTypeFilter, assetStatusFilter], ([s, t, st]) => {
  if (!import.meta.client) return
  try {
    localStorage.setItem(FILTERS_KEY, JSON.stringify({ assetSearch: s, assetTypeFilter: t, assetStatusFilter: st }))
  } catch {}
})

// 新建资产类型下拉（仅展示类资产；股票/基金/债券/黄金请去投资页）
const assetTypeItems = [
  { label: '现金', value: 'cash' },
  { label: '存款', value: 'savings' },
  { label: '养老金', value: 'pension' },
  { label: '房产', value: 'property' },
  { label: '其他', value: 'other' },
]
const liquidityItems = [
  { label: '高（随时可取）', value: 'high' },
  { label: '中', value: 'medium' },
  { label: '低（锁定期）', value: 'low' },
]
const assetTypeFilterItems = [
  { label: '全部类型', value: '' },
  { label: '现金', value: 'cash' },
  { label: '存款', value: 'savings' },
  { label: '基金', value: 'fund' },
  { label: '股票', value: 'stock' },
  { label: '债券', value: 'bond' },
  { label: '银行理财', value: 'wealth_mgmt' },
  { label: '养老金', value: 'pension' },
  { label: '黄金', value: 'gold' },
  { label: '房产', value: 'property' },
  { label: '其他', value: 'other' },
]
const assetStatusFilterItems = [
  { label: '全部状态', value: '' },
  { label: '活跃', value: 'active' },
  { label: '冻结', value: 'frozen' },
  { label: '已关闭', value: 'closed' },
]
const liabilityTypeItems = [
  { label: '信用卡', value: 'credit_card' },
  { label: '信用卡分期', value: 'credit_card_installment' },
  { label: '花呗', value: 'huabei' },
  { label: '白条', value: 'baitiao' },
  { label: '车贷', value: 'car_loan' },
  { label: '房贷', value: 'mortgage' },
  { label: '贷款', value: 'loan' },
  { label: '其他', value: 'other' },
]
const bankItems = [
  { label: '手动设置', value: '' },
  { label: '招商银行', value: 'cmb' },
  { label: '工商银行', value: 'icbc' },
  { label: '建设银行', value: 'ccb' },
  { label: '农业银行', value: 'abc' },
  { label: '中国银行', value: 'boc' },
  { label: '民生银行', value: 'cmbc' },
  { label: '兴业银行', value: 'cib' },
  { label: '浦发银行', value: 'spdb' },
  { label: '中信银行', value: 'citic' },
  { label: '广发银行', value: 'gdb' },
]
const billingDayItems = Array.from({ length: 28 }, (_, i) => ({ label: `${i + 1}号`, value: i + 1 }))

// 删除确认弹窗（替代 confirm，文案点出名称+金额）
const pendingDelete = ref<{ kind: 'asset' | 'liability', id: number, name: string, amount?: string } | null>(null)
const deleteConfirmOpen = computed({
  get: () => !!pendingDelete.value,
  set: (v: boolean) => { if (!v) pendingDelete.value = null }
})
const requestDeleteAsset = (a) => { pendingDelete.value = { kind: 'asset', id: a.id, name: a.name, amount: Number(a.current_value || 0).toFixed(2) } }
const requestDeleteLiability = (l) => { pendingDelete.value = { kind: 'liability', id: l.id, name: l.name, amount: Number(l.current_amount || 0).toFixed(2) } }
const confirmDelete = async () => {
  if (!pendingDelete.value) return
  actionError.value = ''
  try {
    if (pendingDelete.value.kind === 'asset') await deleteAsset(pendingDelete.value.id)
    else await deleteLiability(pendingDelete.value.id)
    pendingDelete.value = null
    await loadData()
  } catch (e) {
    console.error(e)
    actionError.value = '删除失败：' + (e?.message || '未知错误')
  }
}

const goldPrice = ref(0)
const goldPriceState = ref<'idle' | 'loading' | 'ok' | 'error'>('idle')
const goldManualPrice = ref(0)
const form = ref({
  name: '', asset_type: 'savings', account: '', current_value: 0, initial_value: 0, liquidity: 'medium', notes: ''
})

const liabilityForm = ref({
  name: '', liability_type: 'credit_card', total_amount: 0, current_amount: 0, interest_rate: 0, due_date: '',
  min_payment: 0, bill_date: '', billing_day: 1
})
const editingLiabilityId = ref(null)
const selectedBank = ref('')
const repaymentDaysOffset = ref(20)  // 默认账单日后 20 天还款

// 主流银行信用卡账单日/还款日规则
const bankRules = {
  cmb: { name: '招商银行', billingDays: [5, 7, 10, 12, 15, 17, 20, 22, 25], repaymentOffset: 18 },
  icbc: { name: '工商银行', billingDays: [1, 5, 10, 12, 15, 20, 25, 28], repaymentOffset: 25 },
  ccb: { name: '建设银行', billingDays: [2, 5, 7, 10, 12, 15, 17, 20, 22, 25, 27], repaymentOffset: 20 },
  abc: { name: '农业银行', billingDays: [5, 10, 15, 20, 25], repaymentOffset: 20 },
  boc: { name: '中国银行', billingDays: [1, 3, 5, 8, 10, 12, 15, 20, 22, 25, 28], repaymentOffset: 20 },
  cmbc: { name: '民生银行', billingDays: [1, 5, 10, 15, 20, 25, 28], repaymentOffset: 20 },
  cib: { name: '兴业银行', billingDays: [5, 10, 15, 20, 25], repaymentOffset: 20 },
  spdb: { name: '浦发银行', billingDays: [5, 10, 15, 20, 25], repaymentOffset: 20 },
  citic: { name: '中信银行', billingDays: [1, 5, 10, 15, 20, 25, 28], repaymentOffset: 20 },
  gdb: { name: '广发银行', billingDays: [5, 10, 15, 20, 25], repaymentOffset: 20 },
}

// 选择银行时自动填充账单日和还款日偏移
const onBankChange = () => {
  if (selectedBank.value && bankRules[selectedBank.value]) {
    const rule = bankRules[selectedBank.value]
    // 自动选择该银行支持的最近账单日
    const today = new Date().getDate()
    const availableDays = rule.billingDays.filter(d => d >= today)
    const suggestedDay = availableDays.length > 0 ? availableDays[0] : rule.billingDays[0]
    liabilityForm.value.billing_day = suggestedDay
    repaymentDaysOffset.value = rule.repaymentOffset
    // 自动计算还款日（当前月份）
    updateDueDate()
  }
}

// 账单日变化时更新还款日
const onBillingDayChange = () => {
  updateDueDate()
}

// 根据账单日和还款日偏移计算还款日
const updateDueDate = () => {
  const billingDay = liabilityForm.value.billing_day
  if (!billingDay) return

  const today = new Date()
  const currentMonth = today.getMonth()
  const currentYear = today.getFullYear()

  // 计算本月账单日
  const billDate = new Date(currentYear, currentMonth, billingDay)

  // 如果今天已经过了本月账单日，用下月账单日
  if (today > billDate) {
    billDate.setMonth(currentMonth + 1)
  }

  // 还款日 = 账单日 + 偏移天数
  const dueDate = new Date(billDate)
  dueDate.setDate(dueDate.getDate() + repaymentDaysOffset.value)

  // 格式化为 YYYY-MM-DD
  const y = dueDate.getFullYear()
  const m = String(dueDate.getMonth() + 1).padStart(2, '0')
  const d = String(dueDate.getDate()).padStart(2, '0')
  liabilityForm.value.due_date = `${y}-${m}-${d}`
}

const totalAssets = computed(() => assets.value.filter(a => a.status === 'active').reduce((s, a) => s + a.current_value, 0))
const totalLiabilities = computed(() => liabilities.value.filter(l => l.status === 'active').reduce((s, l) => s + l.current_amount, 0))
// 顶部家底卡：净值 + 首页同款占比条分母
const netWorth = computed(() => totalAssets.value - totalLiabilities.value)
const assetShare = computed(() => {
  const denom = totalAssets.value + totalLiabilities.value
  if (denom <= 0) return 50
  return (totalAssets.value / denom) * 100
})

// 资产按已有 asset_type 字段分组折叠（组头组内合计），折叠状态客户端持久化
const GROUP_ORDER = ['cash', 'savings', 'fund', 'stock', 'bond', 'wealth_mgmt', 'pension', 'gold', 'property', 'other']
const collapsedGroups = ref<string[]>([])
const GROUPS_KEY = 'sb-assets-groups'
const restoreGroups = () => {
  if (!import.meta.client) return
  try {
    const raw = JSON.parse(localStorage.getItem(GROUPS_KEY) || '[]')
    if (Array.isArray(raw)) collapsedGroups.value = raw.filter(v => typeof v === 'string')
  } catch {}
}
watch(collapsedGroups, (v) => {
  if (!import.meta.client) return
  try {
    localStorage.setItem(GROUPS_KEY, JSON.stringify(v))
  } catch {}
})
const isGroupCollapsed = (t: string) => collapsedGroups.value.includes(t)
const toggleGroup = (t: string) => {
  const i = collapsedGroups.value.indexOf(t)
  if (i >= 0) collapsedGroups.value.splice(i, 1)
  else collapsedGroups.value.push(t)
}
const groupedAssets = computed(() => {
  const map = new Map()
  filteredAssets.value.forEach((a) => {
    const t = a.asset_type || 'other'
    if (!map.has(t)) map.set(t, { type: t, label: typeLabels[t] || t, items: [], total: 0 })
    const g = map.get(t)
    g.items.push(a)
    g.total += a.current_value || 0
  })
  return [...map.values()].sort((a, b) => GROUP_ORDER.indexOf(a.type) - GROUP_ORDER.indexOf(b.type) || b.total - a.total)
})

const pieColors = ['#0F766E', '#3B82F6', '#22C55E', '#F59E0B', '#EF4444', '#8B5CF6', '#EC4899']
const typeLabels = { cash: '现金', savings: '存款', fund: '基金', stock: '股票', bond: '债券', wealth_mgmt: '银行理财', gold: '黄金', pension: '养老金', property: '房产', other: '其他' }

const pieData = computed(() => {
  const active = assets.value.filter(a => a.status === 'active')
  if (!active.length) return []
  const groups = {}
  active.forEach(a => {
    const t = a.asset_type || 'other'
    if (!groups[t]) groups[t] = { value: 0, initial: 0 }
    groups[t].value += a.current_value || 0
    groups[t].initial += a.initial_value || a.current_value || 0
  })
  const total = totalAssets.value || 1
  return Object.entries(groups)
    .map(([type, data]) => ({
      type,
      label: typeLabels[type] || type,
      value: data.value,
      pct: ((data.value / total) * 100).toFixed(1),
      profit: data.value - data.initial,
      profitRate: data.initial > 0 ? (((data.value - data.initial) / data.initial) * 100).toFixed(1) : '0.0'
    }))
    .sort((a, b) => b.value - a.value)
})

// 资产分类饼图 + 净资产曲线 echarts
const { el: assetPieEl, render: renderAssetPie } = useECharts()
watch(pieData, (list) => {
  if (!list.length) return
  renderAssetPie((p) => ({
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
        data: list.map((item, i) => ({
          name: item.label,
          value: item.value,
          itemStyle: { color: pieColors[i % pieColors.length] },
        })),
      },
    ],
  }))
})

const assetCurve = ref({ curve: [], current_net_worth: 0 })
const { el: assetCurveEl, render: renderAssetCurve } = useECharts()
watch(assetCurve, (c) => {
  if (!c.curve?.length) return
  renderAssetCurve((p) => ({
    grid: { left: 8, right: 8, top: 24, bottom: 0, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: p.bg,
      borderColor: p.border,
      textStyle: { color: p.text, fontSize: 12 },
      valueFormatter: (v) => `¥${Number(v).toFixed(0)}`,
    },
    xAxis: {
      type: 'category',
      data: c.curve.map((d) => d.month),
      axisLine: { lineStyle: { color: p.border } },
      axisTick: { show: false },
      axisLabel: { color: p.subtext, fontSize: 11, interval: Math.max(Math.floor(c.curve.length / 8) - 1, 0) },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: p.border, type: 'dashed' } },
      axisLabel: { color: p.subtext, fontSize: 11, formatter: (v) => v >= 10000 ? `${(v / 10000).toFixed(0)}万` : v },
    },
    series: [
      {
        name: '净资产',
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: 5,
        data: c.curve.map((d) => d.estimated_net),
        lineStyle: { color: p.accent, width: 2.5 },
        itemStyle: { color: p.accent },
        areaStyle: { color: p.dark ? 'rgba(45,212,191,0.12)' : 'rgba(15,118,110,0.08)' },
      },
    ],
  }))
}, { deep: true })

const loading = ref(true)
const loadError = ref('')

const loadData = async () => {
  loading.value = true
  loadError.value = ''
  try {
    const [a, l] = await Promise.all([fetchAssets(), fetchLiabilities()])
    assets.value = a
    liabilities.value = l
    // 真实净资产曲线（失败不影响主列表）
    try {
      assetCurve.value = await fetchAssetCurve(12)
    } catch (e) {
      console.error('加载资产曲线失败:', e)
    }
  } catch (e) {
    console.error('加载资产失败:', e)
    const msg = e?.message || ''
    loadError.value = msg || '加载失败'
    // 如果是 401，跳转到登录页
    if (msg.includes('登录已过期')) {
      return
    }
  } finally {
    loading.value = false
  }
}

// 资产同步
const syncing = ref(false)
const syncResult = ref(null)
const lastSyncInfo = ref('')

const syncAssets = async () => {
  syncing.value = true
  syncResult.value = null
  try {
    const res = await triggerAssetSync()
    syncResult.value = {
      message: res.message || '同步完成',
      updated: res.updated || 0,
      failed: res.failed || 0,
      error: res.error || false,
    }
    if (!res.error) {
      await loadData()
      await loadSyncStatus()
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : '未知错误'
    syncResult.value = { message: '同步失败: ' + msg, error: true }
  } finally {
    syncing.value = false
  }
}

const loadSyncStatus = async () => {
  try {
    const res = await fetchSyncStatus()
    if (res.last_sync) {
      const d = new Date(res.last_sync)
      lastSyncInfo.value = `${d.toLocaleDateString()} ${d.toLocaleTimeString()} (${res.last_status || ''})`
    }
  } catch (e) {
    // 静默失败，不影响主流程
  }
}

const handleSubmit = async () => {
  actionError.value = ''
  try {
    if (editingId.value) {
      await updateAsset(editingId.value, form.value)
    } else {
      await createAsset(form.value)
    }
    resetForm()
    showAddForm.value = false
    await loadData()
  } catch (e) {
    console.error(e)
    actionError.value = '保存失败：' + (e?.message || '未知错误')
  }
}

const toggleAddForm = () => {
  showAddForm.value = !showAddForm.value
  if (showAddForm.value) {
    // 打开表单时重置为添加模式
    editingId.value = null
    resetForm()
  }
}

const editAsset = (asset) => {
  editingId.value = asset.id
  form.value = { ...asset }
  showAddForm.value = true
}

const resetForm = () => {
  editingId.value = null
  form.value = { name: '', asset_type: 'savings', account: '', current_value: 0, initial_value: 0, liquidity: 'medium', notes: '', goldGrams: 0, goldCostPerGram: 0 }
}

const handleLiabilitySubmit = async () => {
  actionError.value = ''
  try {
    if (editingLiabilityId.value) {
      await updateLiability(editingLiabilityId.value, liabilityForm.value)
    } else {
      await createLiability(liabilityForm.value)
    }
    liabilityForm.value = { name: '', liability_type: 'credit_card', total_amount: 0, current_amount: 0, interest_rate: 0, due_date: '', min_payment: 0, bill_date: '', billing_day: 1 }
    editingLiabilityId.value = null
    showAddLiabilityForm.value = false
    await loadData()
  } catch (e) {
    console.error(e)
    actionError.value = '保存失败：' + (e?.message || '未知错误')
  }
}

const editLiability = (liab) => {
  editingLiabilityId.value = liab.id
  liabilityForm.value = { ...liab }
  showAddLiabilityForm.value = true
}

const cancelLiabilityEdit = () => {
  editingLiabilityId.value = null
  liabilityForm.value = { name: '', liability_type: 'credit_card', total_amount: 0, current_amount: 0, interest_rate: 0, due_date: '', min_payment: 0, bill_date: '', billing_day: 1 }
  showAddLiabilityForm.value = false
}


const calcGoldValue = () => {
  const px = goldManualPrice.value > 0 ? goldManualPrice.value : goldPrice.value
  if (form.value.asset_type === 'gold' && form.value.goldGrams > 0 && px > 0) {
    form.value.current_value = Math.round(form.value.goldGrams * px * 100) / 100
    if (form.value.goldCostPerGram > 0) {
      form.value.initial_value = Math.round(form.value.goldGrams * form.value.goldCostPerGram * 100) / 100
    }
  }
}

const fetchGoldPrice = async () => {
  goldPriceState.value = 'loading'
  try {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 8000)
    const resp = await fetch('/api/gold-price', { signal: ctrl.signal })
    clearTimeout(timer)
    if (resp.ok) {
      const data = await resp.json()
      goldPrice.value = data.price
      goldPriceState.value = 'ok'
    } else {
      goldPriceState.value = 'error'
    }
  } catch (e) {
    console.error('获取金价失败:', e)
    goldPriceState.value = 'error'
  }
}

onMounted(() => { restoreFilters(); restoreGroups(); loadData(); loadSyncStatus(); fetchGoldPrice() })
onActivated(loadData) // 客户端路由导航回来时也重新加载
</script>

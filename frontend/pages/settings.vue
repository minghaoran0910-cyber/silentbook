<template>
  <div class="mx-auto min-w-0 w-full max-w-3xl px-4 py-6">
    <h1 class="mb-6 text-2xl font-semibold" :style="{ color: 'var(--text-primary)' }">
      设置
    </h1>

    <!-- 外观：品牌三选 + 深浅切换（主题切换沿用导航栏，此处为同源快捷入口） -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">外观</h2>
      <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">
        三品牌 × 深浅同源，与导航栏同一套状态（调 useBrandTheme）
      </p>
      <div class="flex min-w-0 flex-wrap items-center gap-2" role="group" aria-label="品牌三选">
        <UButton
          v-for="b in brands"
          :key="b.id"
          :variant="brand === b.id ? 'solid' : 'outline'"
          color="primary"
          size="sm"
          :aria-pressed="brand === b.id"
          :title="b.label + '·' + b.hint"
          @click="setBrand(b.id as Brand)"
        >
          {{ b.label }}
        </UButton>
        <span class="ml-1 hidden text-xs min-[480px]:inline" :style="{ color: 'var(--text-tertiary)' }">
          {{ currentBrandHint }}
        </span>
      </div>
      <div class="mt-4 flex min-w-0 flex-wrap items-center justify-between gap-2 border-t pt-4" :style="{ borderColor: 'var(--border)' }">
        <span class="text-sm" :style="{ color: 'var(--text-primary)' }">
          深色模式
          <span class="ml-1 text-xs" :style="{ color: 'var(--text-secondary)' }">（当前：{{ theme === 'dark' ? '深色' : '浅色' }}）</span>
        </span>
        <USwitch :model-value="theme === 'dark'" aria-label="深浅切换" @update:model-value="toggle()" />
      </div>
    </UCard>

    <!-- 通知源管理 -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">通知源</h2>
      <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">配置要解析的银行/支付平台通知</p>
      <div class="flex min-w-0 flex-col gap-2">
        <div
          v-for="source in sources"
          :key="source.id"
          class="flex min-w-0 items-center justify-between gap-3 rounded-lg px-3 py-2"
          :style="{ background: 'var(--bg-primary)' }"
        >
          <div class="flex min-w-0 items-center gap-2">
            <AppIcon :icon="source.icon" :size="20" />
            <span class="truncate text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ source.name }}</span>
          </div>
          <USwitch
            v-model="source.enabled"
            :aria-label="'启用' + source.name"
            @update:model-value="() => saveSource(source)"
          />
        </div>
      </div>
    </UCard>

    <!-- AI 分析模式 + 自定义模型 + OpenClaw 绑定 + Agent 开关 -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">AI Agent</h2>
      <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">配置分析用的 AI Agent</p>

      <div class="flex min-w-0 flex-wrap items-center justify-between gap-2 border-b pb-4" :style="{ borderColor: 'var(--border)' }">
        <span class="text-sm" :style="{ color: 'var(--text-primary)' }">分析模式</span>
        <USelect
          v-model="agentMode"
          :items="agentModeItems"
          value-key="value"
          placeholder="选择分析模式"
          aria-label="分析模式"
          class="w-full min-w-0 min-[480px]:w-56"
          @update:model-value="saveAgentMode"
        />
      </div>

      <!-- 自定义模型配置 -->
      <div class="mt-4 rounded-lg border p-4" :style="{ background: 'var(--bg-primary)', borderColor: 'var(--border)' }">
        <h3 class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">自定义模型配置</h3>
        <p class="mb-3 mt-1 text-xs" :style="{ color: 'var(--text-secondary)' }">填写你自己的 API 参数，分析时将使用此模型</p>
        <div class="flex min-w-0 flex-col gap-3">
          <div class="min-w-0">
            <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="ai-base">API Base URL</label>
            <UInput
              id="ai-base"
              v-model="aiConfig.api_base"
              type="text"
              placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
              class="w-full min-w-0"
            />
          </div>
          <div class="min-w-0">
            <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="ai-key">API Key</label>
            <UInput
              id="ai-key"
              v-model="aiConfig.api_key"
              :type="showApiKey ? 'text' : 'password'"
              :placeholder="aiConfig.api_key_masked || 'sk-...'"
              class="w-full min-w-0"
            >
              <template #trailing>
                <UButton
                  variant="ghost"
                  color="neutral"
                  size="xs"
                  square
                  tabindex="-1"
                  :aria-label="showApiKey ? '隐藏' : '显示'"
                  @click="showApiKey = !showApiKey"
                >
                  <template #leading>
                    <AppIcon :icon="showApiKey ? 'EyeSlash' : 'Eye'" :size="16" />
                  </template>
                </UButton>
              </template>
            </UInput>
          </div>
          <div class="min-w-0">
            <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="ai-model">模型名称</label>
            <UInput
              id="ai-model"
              v-model="aiConfig.model_name"
              type="text"
              placeholder="qwen-plus / gpt-4o-mini / glm-4-flash"
              class="w-full min-w-0"
            />
          </div>
          <div class="flex min-w-0 flex-wrap gap-2">
            <UButton color="primary" :loading="savingAiConfig" :disabled="savingAiConfig" @click="saveAiConfig">
              <template #leading>
                <AppIcon v-if="!savingAiConfig" icon="FloppyDisk" :size="15" />
              </template>
              {{ savingAiConfig ? '保存中...' : '保存配置' }}
            </UButton>
            <UButton variant="outline" color="neutral" :loading="testingAiConfig" :disabled="testingAiConfig" @click="testAiConfig">
              <template #leading>
                <AppIcon v-if="!testingAiConfig" icon="PlugsConnected" :size="15" />
              </template>
              {{ testingAiConfig ? '测试中...' : '测试连接' }}
            </UButton>
          </div>
          <UAlert
            v-if="aiConfigMessage"
            :color="aiConfigMessageType === 'success' ? 'success' : 'error'"
            variant="soft"
            :title="aiConfigMessage"
          />
        </div>
      </div>

      <!-- OpenClaw 绑定 -->
      <div class="mt-4 rounded-lg border p-4" :style="{ background: 'var(--bg-primary)', borderColor: 'var(--border)' }">
        <h3 class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">OpenClaw 绑定</h3>
        <p class="mb-3 mt-1 text-xs" :style="{ color: 'var(--text-secondary)' }">绑定你自己的 OpenClaw Agent（在网关里能看到的 agent id），绑定后分析结果可推送给它</p>

        <div v-if="openclawBinding.bound" class="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2" :style="{ borderColor: 'var(--success)' }">
          <span class="flex min-w-0 items-center gap-1 text-sm font-medium" :style="{ color: 'var(--success)' }">
            <AppIcon icon="Check" :size="15" />
            <span class="truncate">已绑定: {{ openclawBinding.agent_label }} ({{ openclawBinding.agent_id }})</span>
            <UBadge color="success" variant="soft" label="已绑定" class="ml-1 shrink-0" />
          </span>
          <UButton color="error" variant="outline" size="sm" @click="showUnbindModal = true">解除绑定</UButton>
        </div>

        <div v-else class="flex min-w-0 flex-col gap-3">
          <div>
            <UButton variant="outline" color="neutral" :loading="fetchingAgents" :disabled="fetchingAgents" @click="fetchOpenClawAgents">
              <template #leading>
                <AppIcon v-if="!fetchingAgents" icon="MagnifyingGlass" :size="15" />
              </template>
              {{ fetchingAgents ? '获取中...' : '自动发现（从网关拉取）' }}
            </UButton>
          </div>
          <div v-if="openclawAgents.length > 0" class="flex min-w-0 flex-col gap-2">
            <button
              v-for="a in openclawAgents"
              :key="a.id"
              type="button"
              class="flex min-w-0 items-center justify-between gap-2 rounded-lg border px-3 py-2 text-left"
              :style="{ background: 'var(--bg-secondary)', borderColor: 'var(--border)' }"
              @click="bindOpenClaw(a)"
            >
              <span class="truncate text-sm" :style="{ color: 'var(--text-primary)' }">{{ a.label || a.id }}</span>
              <span class="shrink-0 font-mono text-xs" :style="{ color: 'var(--text-secondary)' }">{{ a.id }}</span>
            </button>
          </div>
          <UAlert
            v-if="openclawFetchError"
            color="error"
            variant="soft"
            :title="openclawFetchError"
            description="网关不可达？检查后端 OPENCLAW_GATEWAY_URL 是否指向你的网关；Mac 本地可用 host.docker.internal 网关地址，服务器上填网关所在机器的实际地址。连不上就用下面的手动绑定。"
          />
          <div class="border-t border-dashed pt-3" :style="{ borderColor: 'var(--border)' }">
            <div class="mb-2 text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">手动绑定</div>
            <div class="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2">
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="oc-id">Agent ID（网关里的 agent id）</label>
                <UInput id="oc-id" v-model="manualBind.agentId" type="text" placeholder="如：main" class="w-full min-w-0" />
              </div>
              <div class="min-w-0">
                <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="oc-label">显示名（可选）</label>
                <UInput id="oc-label" v-model="manualBind.agentLabel" type="text" placeholder="如：我的主 Agent" class="w-full min-w-0" />
              </div>
            </div>
            <div class="mt-3">
              <UButton color="primary" :loading="bindingManual" :disabled="bindingManual || !manualBind.agentId.trim()" @click="bindManual">
                {{ bindingManual ? '绑定中...' : '绑定' }}
              </UButton>
            </div>
          </div>
        </div>
      </div>

      <!-- 三 Agent 开关 -->
      <div class="mt-4 flex min-w-0 flex-col gap-2">
        <div
          v-for="agent in agents"
          :key="agent.id"
          class="flex min-w-0 items-center justify-between gap-3 rounded-lg px-3 py-2"
          :style="{ background: 'var(--bg-primary)' }"
        >
          <div class="flex min-w-0 items-center gap-2">
            <AppIcon :icon="agent.icon" :size="20" />
            <div class="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span class="text-sm font-medium" :style="{ color: 'var(--text-primary)' }">{{ agent.name }}</span>
              <span class="text-xs" :style="{ color: 'var(--text-secondary)' }">{{ agent.description }}</span>
            </div>
          </div>
          <USwitch
            v-model="agent.enabled"
            :aria-label="'启用' + agent.name"
            @update:model-value="() => saveAgent(agent)"
          />
        </div>
      </div>
    </UCard>

    <!-- 系统：API 地址展示 -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">系统</h2>
      <div class="flex min-w-0 flex-wrap items-center justify-between gap-2 py-2">
        <span class="text-sm" :style="{ color: 'var(--text-primary)' }">API 地址</span>
        <span class="min-w-0 break-all font-mono text-xs" :style="{ color: 'var(--text-secondary)' }">{{ effectiveApiBase }}</span>
      </div>
      <p class="mt-1 text-xs" :style="{ color: 'var(--text-secondary)' }">由部署配置（NUXT_PUBLIC_API_BASE）决定，修改请改环境变量后重启前端。</p>
    </UCard>

    <!-- 账户安全：改密 -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">账户安全</h2>
      <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">修改登录密码（需验证旧密码，成功后请重新登录）</p>
      <div class="grid min-w-0 grid-cols-1 gap-3 min-[480px]:grid-cols-2">
        <div class="min-w-0">
          <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="pwd-old">旧密码</label>
          <UInput
            id="pwd-old"
            v-model="pwdForm.oldPassword"
            :type="showPwd.old ? 'text' : 'password'"
            placeholder="输入旧密码"
            autocomplete="current-password"
            class="w-full min-w-0"
          >
            <template #trailing>
              <UButton variant="ghost" color="neutral" size="xs" square tabindex="-1" :aria-label="showPwd.old ? '隐藏' : '显示'" @click="showPwd.old = !showPwd.old">
                <template #leading>
                  <AppIcon :icon="showPwd.old ? 'EyeSlash' : 'Eye'" :size="16" />
                </template>
              </UButton>
            </template>
          </UInput>
        </div>
        <div class="min-w-0">
          <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="pwd-new">新密码（至少 6 位）</label>
          <UInput
            id="pwd-new"
            v-model="pwdForm.newPassword"
            :type="showPwd.new ? 'text' : 'password'"
            placeholder="输入新密码"
            autocomplete="new-password"
            class="w-full min-w-0"
          >
            <template #trailing>
              <UButton variant="ghost" color="neutral" size="xs" square tabindex="-1" :aria-label="showPwd.new ? '隐藏' : '显示'" @click="showPwd.new = !showPwd.new">
                <template #leading>
                  <AppIcon :icon="showPwd.new ? 'EyeSlash' : 'Eye'" :size="16" />
                </template>
              </UButton>
            </template>
          </UInput>
        </div>
        <div class="min-w-0 min-[480px]:col-span-2">
          <label class="mb-1 block text-xs font-medium" :style="{ color: 'var(--text-secondary)' }" for="pwd-confirm">确认新密码</label>
          <UInput
            id="pwd-confirm"
            v-model="pwdForm.confirmPassword"
            type="password"
            placeholder="再次输入新密码"
            autocomplete="new-password"
            class="w-full min-w-0"
          />
        </div>
      </div>
      <div class="mt-4">
        <UButton color="primary" :loading="changingPwd" :disabled="changingPwd" @click="handleChangePassword">
          {{ changingPwd ? '修改中...' : '修改密码' }}
        </UButton>
      </div>
      <UAlert
        v-if="pwdMessage"
        class="mt-3"
        :color="pwdMessageType === 'success' ? 'success' : 'error'"
        variant="soft"
        :title="pwdMessage"
      />
    </UCard>

    <!-- 数据管理：导入导出 CSV/PDF + 分类颜色 + 演示数据 -->
    <UCard
      class="mb-4 min-w-0"
      :style="{ background: 'var(--bg-secondary)', border: '1px solid var(--border)' }"
      :ui="{ body: 'p-5' }"
    >
      <h2 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">数据管理</h2>
      <p class="mb-3 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">导入导出数据</p>

      <div class="flex min-w-0 flex-wrap gap-2">
        <UButton variant="outline" color="neutral" @click="exportData">
          <template #leading>
            <AppIcon icon="DownloadSimple" :size="17" />
          </template>
          导出 CSV
        </UButton>
        <UButton variant="outline" color="neutral" @click="csvInput?.click()">
          <template #leading>
            <AppIcon icon="UploadSimple" :size="17" />
          </template>
          导入 CSV
        </UButton>
        <UButton variant="outline" color="neutral" @click="pdfInput?.click()">
          <template #leading>
            <AppIcon icon="FileText" :size="17" />
          </template>
          导入 PDF 流水
        </UButton>
        <input ref="csvInput" type="file" accept=".csv" class="hidden" @change="importData" />
        <input ref="pdfInput" type="file" accept=".pdf" class="hidden" @change="importPdf" />
      </div>
      <p class="mt-2 text-xs" :style="{ color: 'var(--text-secondary)' }">支持招商银行标准格式 PDF 流水</p>

      <UAlert
        v-if="importResult"
        class="mt-3"
        :color="importResult.success ? 'success' : 'error'"
        variant="soft"
        :title="importResult.message"
      />

      <!-- 分类颜色：datalist 已知分类 + USelect 图标 + 16 色 swatch + color 微调 + 保存/恢复自动 -->
      <div class="mt-5 border-t border-dashed pt-4" :style="{ borderColor: 'var(--border)' }">
        <div class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">
          分类颜色
          <span class="ml-1 text-xs font-normal" :style="{ color: 'var(--text-secondary)' }">未知分类自动配色，可手动覆盖</span>
        </div>
        <p class="mb-3 mt-1 text-xs" :style="{ color: 'var(--text-secondary)' }">给任意分类（含 AI 自建的）指定颜色，图标按关键词自动匹配</p>
        <div class="flex min-w-0 flex-wrap items-center gap-2">
          <UInput
            v-model="colorEdit.name"
            type="text"
            placeholder="分类名，如：宠物医疗"
            list="sb-cat-list"
            aria-label="分类名"
            class="min-w-36 flex-1"
            @change="onColorEditName"
          />
          <datalist id="sb-cat-list">
            <option v-for="c in knownCategories" :key="c" :value="c" />
          </datalist>
          <USelect
            v-model="colorEdit.icon"
            :items="iconChoiceItems"
            value-key="value"
            placeholder="图标"
            aria-label="选择图标"
            class="w-32 min-w-0"
          />
          <span class="inline-flex shrink-0 items-center gap-1" title="当前图标预览">
            <AppIcon :icon="colorEdit.icon" :size="18" />
          </span>
          <input
            v-model="colorEdit.color"
            type="color"
            aria-label="微调颜色"
            class="sb-color-input h-9 w-10 shrink-0 cursor-pointer rounded"
            :style="{ border: '1px solid var(--border)', background: 'var(--bg-primary)' }"
          />
          <UButton variant="outline" color="neutral" size="sm" :disabled="!colorEdit.name.trim()" @click="saveColorEdit">保存</UButton>
        </div>
        <div class="mt-3 flex min-w-0 flex-wrap gap-2" role="group" aria-label="预设色板">
          <button
            v-for="c in categoryPalette"
            :key="c"
            type="button"
            class="sb-palette-dot h-7 w-7 shrink-0 rounded-full"
            :class="{ 'sb-palette-active': colorEdit.color.toUpperCase() === c.toUpperCase() }"
            :style="{ background: c }"
            :title="c"
            :aria-label="'选择颜色 ' + c"
            :aria-pressed="colorEdit.color.toUpperCase() === c.toUpperCase()"
            @click="colorEdit.color = c"
          />
        </div>
        <div v-if="customColorList.length > 0" class="mt-3 flex min-w-0 flex-col gap-2">
          <div
            v-for="item in customColorList"
            :key="item.name"
            class="flex min-w-0 items-center gap-2 rounded border px-2 py-1.5 text-sm"
            :style="{ background: 'var(--bg-primary)', borderColor: 'var(--border)' }"
          >
            <AppIcon :icon="item.style.icon" :color="item.style.color" :size="16" />
            <span class="min-w-0 flex-1 truncate font-medium" :style="{ color: 'var(--text-primary)' }">{{ item.name }}</span>
            <span class="shrink-0 font-mono text-xs" :style="{ color: 'var(--text-secondary)' }">{{ item.style.color }}</span>
            <UButton variant="ghost" color="neutral" size="xs" square title="恢复自动" aria-label="恢复自动配色" @click="resetColorEdit(item.name)">
              <template #leading>
                <AppIcon icon="X" :size="14" />
              </template>
            </UButton>
          </div>
        </div>
      </div>

      <!-- 演示数据 -->
      <div class="mt-5 border-t border-dashed pt-4" :style="{ borderColor: 'var(--border)' }">
        <div class="text-sm font-semibold" :style="{ color: 'var(--text-primary)' }">
          演示数据
          <UBadge v-if="demoStatus.seeded" color="success" variant="soft" label="已载入" class="ml-1" />
        </div>
        <p class="mb-3 mt-1 text-xs" :style="{ color: 'var(--text-secondary)' }">空库体验：载入 3 个月仿真流水 + 资产/预算/目标。库里有数据时不可载入；用“清空交易”可恢复白纸。</p>
        <UButton
          variant="outline"
          color="neutral"
          :loading="seedingDemo"
          :disabled="seedingDemo || demoStatus.transaction_count > 0"
          @click="showSeedModal = true"
        >
          {{ seedingDemo ? '载入中...' : (demoStatus.transaction_count > 0 ? `已有 ${demoStatus.transaction_count} 笔，不可载入` : '载入演示数据') }}
        </UButton>
        <UAlert
          v-if="demoMessage"
          class="mt-3"
          :color="demoMessageType === 'success' ? 'success' : 'error'"
          variant="soft"
          :title="demoMessage"
        />
      </div>
    </UCard>

    <!-- 危险操作确认：载入演示数据 -->
    <UModal v-model:open="showSeedModal" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }">
      <template #content>
        <UCard :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">载入演示数据？</h3>
          <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">将载入 3 个月仿真演示数据，仅空库可用。</p>
          <div class="flex justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="showSeedModal = false">取消</UButton>
            <UButton color="primary" :loading="seedingDemo" @click="confirmSeedDemo">确认载入</UButton>
          </div>
        </UCard>
      </template>
    </UModal>

    <!-- 危险操作确认：解除 OpenClaw 绑定 -->
    <UModal v-model:open="showUnbindModal" :ui="{ content: 'w-[calc(100vw-2rem)] max-w-md' }">
      <template #content>
        <UCard :ui="{ body: 'p-5' }">
          <h3 class="text-base font-semibold" :style="{ color: 'var(--text-primary)' }">解除 OpenClaw 绑定？</h3>
          <p class="mb-4 mt-1 text-sm" :style="{ color: 'var(--text-secondary)' }">
            当前绑定：{{ openclawBinding.agent_label }} ({{ openclawBinding.agent_id }})，解除后分析结果不再推送给它。
          </p>
          <div class="flex justify-end gap-2">
            <UButton variant="outline" color="neutral" @click="showUnbindModal = false">取消</UButton>
            <UButton color="error" @click="confirmUnbindOpenClaw">确认解除</UButton>
          </div>
        </UCard>
      </template>
    </UModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onActivated } from 'vue'
import { getSources, updateSources, getAgentConfigs, updateAgentConfig, fetchAiConfig, updateAiConfig, testAiConfigConnection, fetchOpenClawAgents as fetchOpenClawAgentsApi, fetchOpenClawBinding, bindOpenClawAgent, unbindOpenClawAgent, updateSettings as updateSettingsApi, getApiBaseUrl, downloadExportCsv, importCsvContent, importPdfFile, changePassword as changePasswordApi, clearAuth, fetchDemoStatus, seedDemoData } from '~/utils/api'
import { categoryIcons, getCategoryIcon, loadCustomCategoryStyles, saveCustomCategoryStyle, resetCustomCategoryStyle, CATEGORY_PALETTE, ICON_CHOICES, getAllKnownCategories } from '~/utils/icons'
import { useBrandTheme } from '~/composables/useBrandTheme'
import type { Brand } from '~/composables/useBrandTheme'

void categoryIcons

const toast = useToast()
const { brand, theme, setBrand, toggle, brands } = useBrandTheme()
const currentBrandHint = computed(() => brands.find((b) => b.id === brand.value)?.hint || '')

interface Source { id: string; name: string; icon: string; enabled: boolean }
interface Agent { id: number; name: string; icon: string; description: string; enabled: boolean }

const sources = ref<Source[]>([
  { id: 'cmb', name: '招商银行', icon: 'Bank', enabled: true },
  { id: 'icbc', name: '工商银行', icon: 'Bank', enabled: true },
  { id: 'ccb', name: '建设银行', icon: 'Bank', enabled: true },
  { id: 'alipay', name: '支付宝', icon: 'Wallet', enabled: true },
  { id: 'wechat_pay', name: '微信支付', icon: 'DeviceMobile', enabled: true }
])

const agents = ref<Agent[]>([
  { id: 1, name: '消费分析', icon: 'ChartLine', description: '支出结构与异常消费分析', enabled: true },
  { id: 2, name: '投资分析', icon: 'TrendUp', description: '资产配置与收益分析', enabled: true },
  { id: 3, name: '综合建议', icon: 'BookOpen', description: '财务健康度与行动建议', enabled: true }
])

const agentMode = ref('auto')
const agentModeItems = [
  { label: '自动（优先 OpenClaw）', value: 'auto' },
  { label: 'OpenClaw（三 Agent）', value: 'openclaw' },
  { label: '本地 LLM', value: 'local' }
]
// 当前生效的后端地址（只读展示，由部署配置决定，不可在此修改）
const effectiveApiBase = ref('/api')
const importResult = ref<{ success: boolean; message: string } | null>(null)

const csvInput = ref<HTMLInputElement | null>(null)
const pdfInput = ref<HTMLInputElement | null>(null)
const showSeedModal = ref(false)
const showUnbindModal = ref(false)

// 分类颜色自定义（覆盖内置精选与自动配色，存 localStorage）
const colorEdit = ref({ name: '', color: CATEGORY_PALETTE[0], icon: 'Tag' })
const customColorList = ref<Array<{ name: string; style: { icon: string; color: string } }>>([])
const categoryPalette = CATEGORY_PALETTE
const iconChoiceItems = computed(() => ICON_CHOICES.map((o) => ({ label: o.label, value: o.value })))
const knownCategories = computed(() => getAllKnownCategories())

const refreshCustomColors = () => {
  const all = loadCustomCategoryStyles()
  customColorList.value = Object.entries(all).map(([name, style]) => ({ name, style }))
}

// 输入分类名后，预填当前生效的 icon+color（自定义 > 内置 > 自动），再由用户点选覆盖
const onColorEditName = () => {
  const name = colorEdit.value.name.trim()
  if (!name) return
  const current = getCategoryIcon(name)
  colorEdit.value.icon = current.icon || 'Tag'
  colorEdit.value.color = current.color || CATEGORY_PALETTE[0]
}

const saveColorEdit = () => {
  const name = colorEdit.value.name.trim()
  if (!name) return
  saveCustomCategoryStyle(name, { icon: colorEdit.value.icon || 'Tag', color: colorEdit.value.color })
  colorEdit.value = { name: '', color: CATEGORY_PALETTE[0], icon: 'Tag' }
  refreshCustomColors()
  toast.add({ title: '分类颜色已保存', color: 'success' })
}

const resetColorEdit = (name: string) => {
  resetCustomCategoryStyle(name)
  refreshCustomColors()
  toast.add({ title: `已恢复「${name}」自动配色`, color: 'neutral' })
}

// 演示数据
const demoStatus = ref({ seeded: false, transaction_count: 0, seeded_at: '' })
const seedingDemo = ref(false)
const demoMessage = ref('')
const demoMessageType = ref('')

const loadDemoStatus = async () => {
  try {
    demoStatus.value = await fetchDemoStatus()
  } catch (e) {
    console.error('加载演示状态失败:', e)
  }
}

const confirmSeedDemo = async () => {
  showSeedModal.value = false
  seedingDemo.value = true
  demoMessage.value = ''
  try {
    const r = await seedDemoData()
    demoMessage.value = r.message || '载入成功，去首页看看'
    demoMessageType.value = 'success'
    toast.add({ title: demoMessage.value, color: 'success' })
    await loadDemoStatus()
  } catch (e) {
    demoMessage.value = '载入失败: ' + ((e as Error).message || '未知错误')
    demoMessageType.value = 'error'
    toast.add({ title: demoMessage.value, color: 'error' })
  } finally {
    seedingDemo.value = false
  }
}

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
    toast.add({ title: pwdMessage.value, color: 'error' })
    return
  }
  if (pwdForm.value.newPassword.length < 6) {
    pwdMessage.value = '新密码至少 6 位'
    pwdMessageType.value = 'error'
    toast.add({ title: pwdMessage.value, color: 'error' })
    return
  }
  if (pwdForm.value.newPassword !== pwdForm.value.confirmPassword) {
    pwdMessage.value = '两次输入的新密码不一致'
    pwdMessageType.value = 'error'
    toast.add({ title: pwdMessage.value, color: 'error' })
    return
  }
  changingPwd.value = true
  try {
    await changePasswordApi(pwdForm.value.oldPassword, pwdForm.value.newPassword)
    pwdMessage.value = '密码修改成功，正在跳转重新登录…'
    pwdMessageType.value = 'success'
    toast.add({ title: pwdMessage.value, color: 'success' })
    pwdForm.value = { oldPassword: '', newPassword: '', confirmPassword: '' }
    setTimeout(() => {
      clearAuth()
      navigateTo('/auth')
    }, 1200)
  } catch (e) {
    pwdMessage.value = '修改失败: ' + ((e as Error).message || '未知错误')
    pwdMessageType.value = 'error'
    toast.add({ title: pwdMessage.value, color: 'error' })
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
    toast.add({ title: '导出成功', color: 'success' })
  } catch (e) {
    importResult.value = { success: false, message: '导出失败: ' + (e as Error).message }
    toast.add({ title: importResult.value.message, color: 'error' })
  }
}

const importData = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const reader = new FileReader()
  reader.onload = async (e) => {
    const content = e.target?.result as string
    try {
      const result = await importCsvContent(content)
      importResult.value = { success: true, message: `导入成功: ${result.imported} 条记录` }
      toast.add({ title: importResult.value.message, color: 'success' })
    } catch (err) {
      importResult.value = { success: false, message: '导入失败: ' + (err as Error).message }
      toast.add({ title: importResult.value.message, color: 'error' })
    } finally {
      input.value = ''
    }
  }
  reader.readAsText(file)
}

const importPdf = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  importResult.value = { success: true, message: '正在解析 PDF...' }

  try {
    const result = await importPdfFile(file)

    if (result.status === 'ok') {
      importResult.value = { success: true, message: `${result.bank} | 成功导入 ${result.imported} 条记录` }
      toast.add({ title: importResult.value.message, color: 'success' })
    } else if (result.status === 'warning') {
      importResult.value = { success: false, message: `${result.message}` }
      toast.add({ title: importResult.value.message, color: 'warning' })
    } else {
      importResult.value = { success: false, message: `导入失败：${result.detail || '未知错误'}` }
      toast.add({ title: importResult.value.message, color: 'error' })
    }
  } catch (err) {
    importResult.value = { success: false, message: 'PDF 导入失败: ' + (err as Error).message }
    toast.add({ title: importResult.value.message, color: 'error' })
  } finally {
    input.value = ''
  }
}

const saveAgentMode = async () => {
  try {
    await updateSettingsApi({ agent_mode: agentMode.value })
    toast.add({ title: '分析模式已保存', color: 'success' })
  } catch (e) {
    console.error('保存分析模式失败:', e)
    toast.add({ title: '保存分析模式失败', color: 'error' })
  }
}

const saveSource = async (source: Source) => {
  try {
    const map: Record<string, boolean> = {}
    sources.value.forEach((s) => { map[s.id] = s.enabled })
    await updateSources(map)
  } catch (e) {
    source.enabled = !source.enabled
    toast.add({ title: '保存通知源失败', color: 'error' })
  }
}

const saveAgent = async (agent: Agent) => {
  try {
    await updateAgentConfig(agent.id, { is_active: agent.enabled })
  } catch (e) {
    agent.enabled = !agent.enabled
    toast.add({ title: '保存 Agent 开关失败', color: 'error' })
  }
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
    toast.add({ title: aiConfigMessage.value, color: 'success' })
    if (resp.api_key_masked) aiConfig.value.api_key_masked = resp.api_key_masked
    aiConfig.value.api_key = ''  // 清空输入框
  } catch (e) {
    aiConfigMessage.value = '保存失败: ' + ((e as Error).message || e)
    aiConfigMessageType.value = 'error'
    toast.add({ title: aiConfigMessage.value, color: 'error' })
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
      toast.add({ title: resp.message, color: 'success' })
    } else {
      aiConfigMessage.value = resp.message
      aiConfigMessageType.value = 'error'
      toast.add({ title: resp.message, color: 'error' })
    }
  } catch (e) {
    aiConfigMessage.value = '测试失败: ' + ((e as Error).message || e)
    aiConfigMessageType.value = 'error'
    toast.add({ title: aiConfigMessage.value, color: 'error' })
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
const openclawAgents = ref<Array<{ id: string; label?: string }>>([])
const fetchingAgents = ref(false)
const openclawFetchError = ref('')
const manualBind = ref({ agentId: '', agentLabel: '' })
const bindingManual = ref(false)

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
    openclawFetchError.value = '连接失败: ' + ((e as Error).message || e)
  } finally {
    fetchingAgents.value = false
  }
}

const bindOpenClaw = async (agent: { id: string; label?: string }) => {
  try {
    const resp = await bindOpenClawAgent(agent.id, agent.label || agent.id)
    openclawBinding.value = resp
    openclawAgents.value = []
    toast.add({ title: 'OpenClaw 绑定成功', color: 'success' })
  } catch (e) {
    openclawFetchError.value = '绑定失败: ' + ((e as Error).message || e)
    toast.add({ title: openclawFetchError.value, color: 'error' })
  }
}

const bindManual = async () => {
  const agentId = manualBind.value.agentId.trim()
  if (!agentId) return
  bindingManual.value = true
  openclawFetchError.value = ''
  try {
    const resp = await bindOpenClawAgent(
      agentId, manualBind.value.agentLabel.trim() || agentId)
    openclawBinding.value = resp
    manualBind.value = { agentId: '', agentLabel: '' }
    toast.add({ title: 'OpenClaw 绑定成功', color: 'success' })
  } catch (e) {
    openclawFetchError.value = '绑定失败: ' + ((e as Error).message || e)
    toast.add({ title: openclawFetchError.value, color: 'error' })
  } finally {
    bindingManual.value = false
  }
}

const confirmUnbindOpenClaw = async () => {
  showUnbindModal.value = false
  try {
    await unbindOpenClawAgent()
    openclawBinding.value = { bound: false, agent_id: '', agent_label: '' }
    toast.add({ title: '已解除 OpenClaw 绑定', color: 'neutral' })
  } catch (e) {
    console.error('解除绑定失败:', e)
    toast.add({ title: '解除绑定失败', color: 'error' })
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
    sources.value.forEach((s) => { s.enabled = srcMap[s.id] !== false })

    const agentList = await getAgentConfigs()
    if (agentList.length > 0) {
      agents.value = agentList.map((a: { id: number; name: string; system_prompt?: string; is_active: boolean }) => ({
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
  // 演示数据状态
  await loadDemoStatus()
  // 自定义分类颜色
  refreshCustomColors()
}
onMounted(loadAll)
onActivated(loadAll)
</script>

<style scoped>
.sb-color-input {
  padding: 2px;
}
.sb-palette-dot {
  border: 2px solid transparent;
  padding: 0;
  cursor: pointer;
}
.sb-palette-active {
  border-color: var(--text-primary);
  box-shadow: 0 0 0 2px var(--bg-primary), 0 0 0 4px var(--text-primary);
}
@media (prefers-reduced-motion: reduce) {
  .sb-palette-dot {
    transition: none;
  }
}
@media (max-width: 480px) {
  .sb-color-input {
    width: 2.5rem;
  }
}
</style>

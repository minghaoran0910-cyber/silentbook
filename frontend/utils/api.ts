export interface Transaction {
  id: number
  amount: number
  category: string
  account: string
  description: string | null
  transaction_type: 'income' | 'expense'
  raw_text: string | null
  confidence: number
  parsed_at: string
}

export interface DashboardStats {
  net_assets: number
  monthly_income: number
  monthly_expenses: number
  transaction_count: number
}

export interface AnalysisResult {
  consumption: string
  investment: string
  suggestion: string
  mode?: string
}

export interface ParseRequest {
  title: string
  body: string
  source?: string
}

export interface CreateTransactionPayload {
  amount: number
  category: string
  account: string
  description?: string
  transaction_type: 'income' | 'expense'
  raw_text?: string
  confidence?: number
}

export interface UpdateTransactionPayload {
  amount?: number
  category?: string
  account?: string
  description?: string
  transaction_type?: 'income' | 'expense'
  raw_text?: string
  confidence?: number
}

// SSR 端用 Docker 内部网络，浏览器端用 nginx 代理的 /api 前缀
function getApiBase(): string {
  if (import.meta.server) {
    return process.env.NUXT_SSR_API_BASE || 'http://backend:8000'
  }
  // 浏览器端：用 Nuxt runtimeConfig（NUXT_PUBLIC_* 在客户端只能通过 runtimeConfig 访问）
  try {
    const config = useRuntimeConfig()
    if (config.public?.apiBase) return config.public.apiBase as string
  } catch {}
  return '/api'
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const apiBase = getApiBase()
  const fullUrl = apiBase.startsWith('/') ? `${apiBase}${url}` : `${apiBase}${url}`
  
  // 自动附加 Authorization header
  const headers = new Headers(options?.headers)
  if (!headers.has('Authorization')) {
    let token: string | null = null
    if (import.meta.client) {
      token = localStorage.getItem('auth_token')
    } else {
      // SSR: 从 cookie 读取 token（需要 middleware 将 cookie 同步到请求中）
      try {
        const event = useRequestHeaders(['cookie'])
        const cookieHeader = event?.cookie || ''
        const match = cookieHeader.match(/auth_token=([^;]+)/)
        if (match) token = match[1]
      } catch {}
    }
    if (token) {
      headers.set('Authorization', `Bearer ${token}`)
    }
  }
  
  const response = await fetch(fullUrl, { ...options, headers })
  if (!response.ok) {
    // 401 时清除过期 token 并跳转登录（静默处理，不抛错）
    if (response.status === 401 && import.meta.client) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('user_info')
      if (window.location.pathname !== '/auth') {
        window.location.href = '/auth'
      }
      throw new Error('登录已过期，请重新登录')
    }
    // SSR 401: 静默返回空数据，让客户端重新加载
    if (response.status === 401 && import.meta.server) {
      return [] as T  // 返回空数组/对象，避免 SSR 崩溃
    }
    const detail = await response.text().catch(() => '')
    throw new Error(`API error ${response.status}: ${detail}`)
  }
  return response.json()
}

// ===== Transactions =====

export async function fetchTransactions(params?: {
  account?: string
  category?: string
  transaction_type?: string
  limit?: number
}): Promise<Transaction[]> {
  const searchParams = new URLSearchParams()
  if (params?.account) searchParams.append('account', params.account)
  if (params?.category) searchParams.append('category', params.category)
  if (params?.transaction_type) searchParams.append('transaction_type', params.transaction_type)
  if (params?.limit) searchParams.append('limit', params.limit.toString())

  return request<Transaction[]>(`/transactions?${searchParams}`)
}

export async function createTransaction(data: CreateTransactionPayload): Promise<Transaction> {
  return request<Transaction>('/transactions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function updateTransaction(id: number, data: UpdateTransactionPayload): Promise<Transaction> {
  return request<Transaction>(`/transactions/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function deleteTransaction(id: number): Promise<void> {
  await request(`/transactions/${id}`, { method: 'DELETE' })
}

export async function deleteAllTransactions(): Promise<void> {
  await request('/transactions?confirm=true', { method: 'DELETE' })
}

// ===== Stats =====

export async function fetchDashboardStats(): Promise<DashboardStats> {
  return request<DashboardStats>('/stats/dashboard')
}

export interface TrendData {
  daily: { date: string; income: number; expense: number; count: number }[]
  categories: { name: string; amount: number }[]
  total_expense: number
  total_income: number
}

export async function fetchTrend(days: number = 30): Promise<TrendData> {
  return request<TrendData>(`/stats/trend?days=${days}`)
}

export interface MonthlyReport {
  year: number
  month: number
  total_income: number
  total_expense: number
  net: number
  savings_rate: number
  daily_avg_expense: number
  transaction_count: number
  income_categories: { name: string; amount: number }[]
  expense_categories: { name: string; amount: number }[]
  weekly: { week: number; income: number; expense: number; count: number }[]
}

export async function fetchMonthlyReport(year?: number, month?: number): Promise<MonthlyReport> {
  const params = new URLSearchParams()
  if (year) params.append('year', String(year))
  if (month) params.append('month', String(month))
  const q = params.toString() ? `?${params.toString()}` : ''
  return request<MonthlyReport>(`/stats/monthly${q}`)
}

// ===== Analysis =====

export async function runAnalysis(): Promise<AnalysisResult> {
  return request<AnalysisResult>('/analyze', { method: 'POST' })
}

export async function fetchLatestAnalysis(): Promise<AnalysisResult> {
  return request<AnalysisResult>('/analysis/latest')
}

export interface AnalysisHistoryItem {
  created_at: string
  items: { id: number; analysis_type: string; content: string; agent_name: string }[]
}

export async function fetchAnalysisHistory(limit: number = 20): Promise<AnalysisHistoryItem[]> {
  return request<AnalysisHistoryItem[]>(`/analysis/history?limit=${limit}`)
}

// ===== Parse =====

export async function parseNotification(notification: ParseRequest): Promise<{ message: string; id: number }> {
  return request('/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(notification)
  })
}

// ===== 资产管理 =====

export interface Asset {
  id: number
  name: string
  asset_type: string
  account: string | null
  current_value: number
  initial_value: number
  currency: string
  liquidity: string
  status: string
  notes: string | null
  created_at: string
  updated_at: string
}

export interface Liability {
  id: number
  name: string
  liability_type: string
  total_amount: number
  current_amount: number
  interest_rate: number
  monthly_payment: number | null
  remaining_periods: number | null
  due_date: string | null
  status: string
  notes: string | null
  created_at: string
  updated_at: string
}

export async function fetchAssets(params?: { asset_type?: string; status?: string }): Promise<Asset[]> {
  const searchParams = new URLSearchParams()
  if (params?.asset_type) searchParams.append('asset_type', params.asset_type)
  if (params?.status) searchParams.append('status', params.status)
  return request<Asset[]>(`/assets?${searchParams}`)
}

export async function createAsset(data: Partial<Asset>): Promise<Asset> {
  return request<Asset>('/assets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function updateAsset(id: number, data: Partial<Asset>): Promise<Asset> {
  return request<Asset>(`/assets/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function deleteAsset(id: number): Promise<void> {
  await request(`/assets/${id}`, { method: 'DELETE' })
}

export async function fetchLiabilities(params?: { liability_type?: string; status?: string }): Promise<Liability[]> {
  const searchParams = new URLSearchParams()
  if (params?.liability_type) searchParams.append('liability_type', params.liability_type)
  if (params?.status) searchParams.append('status', params.status)
  return request<Liability[]>(`/liabilities?${searchParams}`)
}

export async function createLiability(data: Partial<Liability>): Promise<Liability> {
  return request<Liability>('/liabilities', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function updateLiability(id: number, data: Partial<Liability>): Promise<Liability> {
  return request<Liability>(`/liabilities/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function deleteLiability(id: number): Promise<void> {
  await request(`/liabilities/${id}`, { method: 'DELETE' })
}

// ===== 设置 =====
export async function getSettings(): Promise<Record<string, string>> {
  return request('/settings')
}

export async function updateSettings(items: Record<string, any>): Promise<any> {
  return request('/settings', { method: 'PUT', body: JSON.stringify(items), headers: { 'Content-Type': 'application/json' } })
}

export async function getSources(): Promise<Record<string, boolean>> {
  return request('/settings/sources')
}

export async function updateSources(sources: Record<string, boolean>): Promise<any> {
  return request('/settings/sources', { method: 'PUT', body: JSON.stringify(sources), headers: { 'Content-Type': 'application/json' } })
}

export async function getAgentConfigs(): Promise<any[]> {
  return request('/settings/agents')
}

export async function updateAgentConfig(agentId: number, data: Record<string, any>): Promise<any> {
  return request(`/settings/agents/${agentId}`, { method: 'PUT', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json' } })
}

// ===== 用户认证 =====

export interface UserInfo {
  id: number
  email: string | null
  phone: string | null
  nickname: string | null
  is_active: boolean
  created_at: string
}

export interface TokenData {
  access_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}

export async function register(data: {
  email?: string
  phone?: string
  password: string
  nickname?: string
}): Promise<TokenData> {
  return request<TokenData>('/auth/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function login(account: string, password: string): Promise<TokenData> {
  return request<TokenData>('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ account, password })
  })
}

export async function getCurrentUser(token: string): Promise<UserInfo> {
  return request<UserInfo>('/auth/me', {
    headers: { Authorization: `Bearer ${token}` }
  })
}

export function getStoredToken(): string | null {
  if (import.meta.server) return null
  return localStorage.getItem('auth_token')
}

export function getStoredUser(): UserInfo | null {
  if (import.meta.server) return null
  const raw = localStorage.getItem('user_info')
  return raw ? JSON.parse(raw) : null
}

export function clearAuth() {
  if (import.meta.server) return
  localStorage.removeItem('auth_token')
  localStorage.removeItem('user_info')
}

// ===== 财务目标 =====

export interface FinancialGoal {
  id: number
  name: string
  goal_type: 'savings' | 'debt_payoff' | 'investment' | 'purchase'
  target_amount: number
  current_amount: number
  currency: string
  deadline: string | null
  priority: 'high' | 'medium' | 'low'
  status: 'active' | 'completed' | 'abandoned' | 'paused'
  notes: string | null
  progress_percent: number
  created_at: string
  updated_at: string
}

export interface GoalContribution {
  id: number
  goal_id: number
  amount: number
  description: string | null
  created_at: string
}

export interface GoalSummary {
  total_goals: number
  active_goals: number
  completed_goals: number
  total_target: number
  total_current: number
  overall_progress: number
  goals: FinancialGoal[]
}

export async function fetchGoalsSummary(): Promise<GoalSummary> {
  return request<GoalSummary>('/goals/summary')
}

export async function fetchGoals(params?: { status?: string; priority?: string; goal_type?: string }): Promise<FinancialGoal[]> {
  const searchParams = new URLSearchParams()
  if (params?.status) searchParams.append('status', params.status)
  if (params?.priority) searchParams.append('priority', params.priority)
  if (params?.goal_type) searchParams.append('goal_type', params.goal_type)
  const q = searchParams.toString() ? `?${searchParams.toString()}` : ''
  return request<FinancialGoal[]>(`/goals${q}`)
}

export async function createGoal(data: Partial<FinancialGoal>): Promise<FinancialGoal> {
  return request<FinancialGoal>('/goals', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function updateGoal(id: number, data: Partial<FinancialGoal>): Promise<FinancialGoal> {
  return request<FinancialGoal>(`/goals/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function deleteGoal(id: number): Promise<void> {
  await request(`/goals/${id}`, { method: 'DELETE' })
}

export async function contributeToGoal(goalId: number, amount: number, description?: string): Promise<FinancialGoal> {
  return request<FinancialGoal>(`/goals/${goalId}/contribute`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ amount, description })
  })
}

export async function fetchGoalContributions(goalId: number): Promise<GoalContribution[]> {
  return request<GoalContribution[]>(`/goals/${goalId}/contributions`)
}

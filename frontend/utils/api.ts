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

// SSR 端用 Docker 内部网络，浏览器端用宿主机地址
function getApiBase(): string {
  if (import.meta.server) {
    return process.env.NUXT_SSR_API_BASE || 'http://backend:8000'
  }
  return 'http://localhost:8000'
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${getApiBase()}${url}`, options)
  if (!response.ok) {
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

// ===== Analysis =====

export async function runAnalysis(): Promise<AnalysisResult> {
  return request<AnalysisResult>('/analyze', { method: 'POST' })
}

export async function fetchLatestAnalysis(): Promise<AnalysisResult> {
  return request<AnalysisResult>('/analysis/latest')
}

// ===== Parse =====

export async function parseNotification(notification: ParseRequest): Promise<{ message: string; id: number }> {
  return request('/parse', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(notification)
  })
}

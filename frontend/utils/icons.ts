/**
 * SilentBook 图标系统
 * 资产类型 + 交易分类 + 导航 + 负债类型
 */

// 资产类型图标
export const assetTypeIcons: Record<string, { icon: string; label: string; color: string }> = {
  cash:     { icon: '💰', label: '现金',   color: '#22C55E' },
  savings:  { icon: '🏦', label: '存款',   color: '#3B82F6' },
  fund:     { icon: '📈', label: '基金',   color: '#B45309' },
  stock:    { icon: '📊', label: '股票',   color: '#EF4444' },
  bond:     { icon: '📄', label: '债券',   color: '#8B5CF6' },
  property: { icon: '🏠', label: '房产',   color: '#F59E0B' },
  other:    { icon: '📦', label: '其他',   color: '#6B7280' },
}

// 负债类型图标
export const liabilityTypeIcons: Record<string, { icon: string; label: string; color: string }> = {
  credit_card: { icon: '💳', label: '信用卡', color: '#EF4444' },
  loan:        { icon: '🏦', label: '贷款',   color: '#F59E0B' },
  mortgage:    { icon: '🏡', label: '房贷',   color: '#8B5CF6' },
  other:       { icon: '📦', label: '其他',   color: '#6B7280' },
}

// 交易分类图标
export const categoryIcons: Record<string, { icon: string; color: string }> = {
  '餐饮':    { icon: '🍔', color: '#F59E0B' },
  '交通':    { icon: '🚗', color: '#3B82F6' },
  '购物':    { icon: '🛍', color: '#EC4899' },
  '娱乐':    { icon: '🎮', color: '#8B5CF6' },
  '居住':    { icon: '🏠', color: '#22C55E' },
  '医疗':    { icon: '💊', color: '#EF4444' },
  '教育':    { icon: '📚', color: '#06B6D4' },
  '通讯':    { icon: '📱', color: '#6366F1' },
  '水电':    { icon: '⚡', color: '#FBBF24' },
  '保险':    { icon: '🛡', color: '#10B981' },
  '投资':    { icon: '📈', color: '#B45309' },
  '转账':    { icon: '🔄', color: '#6B7280' },
  '工资':    { icon: '💵', color: '#22C55E' },
  '理财':    { icon: '💎', color: '#8B5CF6' },
  '退款':    { icon: '↩️', color: '#06B6D4' },
  '其他':    { icon: '📦', color: '#6B7280' },
}

// 流动性标签
export const liquidityLabels: Record<string, string> = {
  high: '高（随时可取）',
  medium: '中',
  low: '低（锁定期）',
}

// 状态标签
export const statusLabels: Record<string, { label: string; color: string }> = {
  active:   { label: '活跃',   color: '#22C55E' },
  frozen:   { label: '冻结',   color: '#F59E0B' },
  closed:   { label: '已关闭', color: '#6B7280' },
  paid:     { label: '已还清', color: '#22C55E' },
  overdue:  { label: '逾期',   color: '#EF4444' },
}

// 辅助函数：获取资产类型图标
export function getAssetIcon(type: string) {
  return assetTypeIcons[type] || assetTypeIcons.other
}

// 辅助函数：获取负债类型图标
export function getLiabilityIcon(type: string) {
  return liabilityTypeIcons[type] || liabilityTypeIcons.other
}

// 辅助函数：获取交易分类图标
export function getCategoryIcon(category: string) {
  return categoryIcons[category] || categoryIcons['其他']
}

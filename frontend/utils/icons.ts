/**
 * SilentBook 图标系统
 * 资产类型 + 交易分类 + 负债类型，全部映射到 Phosphor 图标（见 components/AppIcon.vue）。
 * icon 字段是 AppIcon 注册表名，不是 emoji——模板里用 <AppIcon :icon :color> 渲染。
 */

// 资产类型图标
export const assetTypeIcons: Record<string, { icon: string; label: string; color: string }> = {
  cash:     { icon: 'Money',     label: '现金',   color: '#22C55E' },
  savings:  { icon: 'PiggyBank', label: '存款',   color: '#3B82F6' },
  fund:     { icon: 'TrendUp',   label: '基金',   color: '#B45309' },
  stock:    { icon: 'ChartLine', label: '股票',   color: '#EF4444' },
  bond:     { icon: 'Receipt',   label: '债券',   color: '#8B5CF6' },
  property: { icon: 'House',     label: '房产',   color: '#F59E0B' },
  pension: { icon: 'HandCoins', label: '养老金', color: '#059669' },
  gold:    { icon: 'Coins',     label: '黄金',   color: '#D4AF37' },
  other:    { icon: 'Package',   label: '其他',   color: '#6B7280' },
}

// 负债类型图标
export const liabilityTypeIcons: Record<string, { icon: string; label: string; color: string }> = {
  credit_card: { icon: 'CreditCard', label: '信用卡', color: '#EF4444' },
  loan:        { icon: 'Bank',       label: '贷款',   color: '#F59E0B' },
  mortgage:    { icon: 'HouseLine',  label: '房贷',   color: '#8B5CF6' },
  other:       { icon: 'Package',    label: '其他',   color: '#6B7280' },
}

// 交易分类图标（与 notification-parser CATEGORY_KEYWORDS 对齐）
export const categoryIcons: Record<string, { icon: string; color: string }> = {
  '餐饮':    { icon: 'CookingPot',     color: '#F59E0B' },
  '交通':    { icon: 'Car',            color: '#3B82F6' },
  '购物':    { icon: 'ShoppingBag',    color: '#EC4899' },
  '娱乐':    { icon: 'GameController', color: '#8B5CF6' },
  '生活':    { icon: 'Basket',         color: '#65A30D' },
  '金融':    { icon: 'Bank',           color: '#0284C7' },
  '居住':    { icon: 'House',          color: '#22C55E' },
  '医疗':    { icon: 'FirstAid',       color: '#EF4444' },
  '教育':    { icon: 'GraduationCap',  color: '#06B6D4' },
  '通讯':    { icon: 'DeviceMobile',   color: '#6366F1' },
  '水电':    { icon: 'Lightning',      color: '#FBBF24' },
  '保险':    { icon: 'ShieldCheck',    color: '#10B981' },
  '投资':    { icon: 'TrendUp',        color: '#B45309' },
  '转账':    { icon: 'Repeat',         color: '#6B7280' },
  '工资':    { icon: 'CurrencyCny',    color: '#22C55E' },
  '理财':    { icon: 'ChartPieSlice',  color: '#8B5CF6' },
  '退款':    { icon: 'ArrowUUpLeft',   color: '#06B6D4' },
  '数字服务':  { icon: 'Cloud',        color: '#0EA5E9' },
  '自账户划转': { icon: 'Swap',        color: '#6B7280' },
  '人情往来':  { icon: 'Gift',         color: '#E11D48' },
  '储蓄':    { icon: 'PiggyBank',      color: '#059669' },
  '出行旅游':  { icon: 'Airplane',     color: '#38BDF8' },
  '还款':    { icon: 'HandCoins',      color: '#78716C' },
  '水电燃气':  { icon: 'Lightning',    color: '#FBBF24' },
  '政务缴纳':  { icon: 'FileText',     color: '#92400E' },
  '住房':    { icon: 'House',          color: '#22C55E' },
  '家居':    { icon: 'Armchair',       color: '#D946EF' },
  '宠物':    { icon: 'PawPrint',       color: '#16A34A' },
  '其他':    { icon: 'DotsThree',      color: '#6B7280' },
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

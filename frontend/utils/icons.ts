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
  wealth_mgmt: { icon: 'Bank', label: '银行理财', color: '#0284C7' },
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
// 三层解析：用户自定义（localStorage）> 内置精选 > hash 稳定随机（AI 自建分类也永远有色有标）
export function getCategoryIcon(category: string) {
  const custom = loadCustomCategoryStyles()[category]
  if (custom) return custom
  if (categoryIcons[category]) return categoryIcons[category]
  return autoCategoryStyle(category)
}

// 自动调色盘：16 色手工调和，teal 单 accent 体系（首色即 accent 家族），无紫蓝渐变。
// 对比度（实测）：浅底 #f8fafc 下 3.5~7.3，深底 #0b0f14 下 3.0~6.0，全部 ≥ 3:1。
export const CATEGORY_PALETTE = [
  '#0D9488', '#0E7490', '#0284C7', '#0369A1',
  '#16A34A', '#4D7C0F', '#059669', '#B45309',
  '#A16207', '#C2410C', '#DC2626', '#BE123C',
  '#DB2777', '#0F766E', '#78716C', '#64748B',
]

// 兼容旧名：之前内部 12 色 AUTO_PALETTE，现指向同一 16 色盘
// 注意：hash 取模基数由 12 变为 16，未落盘的旧自动色会位移一次，
// 落盘后（assignAutoStyle）即永久稳定。
const AUTO_PALETTE = CATEGORY_PALETTE

const AUTO_ICON_RULES: Array<[RegExp, string]> = [
  [/餐|食|饭|咖啡|茶|外卖/, 'CookingPot'],
  [/车|行|油|铁|票|停车/, 'Car'],
  [/购|淘宝|京东|超市|商场/, 'ShoppingBag'],
  [/影|乐|戏|健身|游/, 'GameController'],
  [/房|租|物业|家|居/, 'House'],
  [/医|药|院|体检/, 'FirstAid'],
  [/学|书|课|考/, 'GraduationCap'],
  [/话|手机|通/, 'DeviceMobile'],
  [/电|水|气|燃/, 'Lightning'],
  [/险|保/, 'ShieldCheck'],
  [/投|股|基|财/, 'TrendUp'],
  [/薪|工资/, 'CurrencyCny'],
  [/退/, 'ArrowUUpLeft'],
  [/存|蓄/, 'PiggyBank'],
  [/还|贷|款/, 'HandCoins'],
  [/政|税|罚/, 'FileText'],
  [/猫|狗|宠/, 'PawPrint'],
  [/飞|航|旅/, 'Airplane'],
  [/衣|饰/, 'ShoppingBag'],
  [/礼|红包|人情/, 'Gift'],
  [/云|数码|会员|订阅/, 'Cloud'],
];

function hashString(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

export function autoCategoryStyle(category: string) {
  const iconRule = AUTO_ICON_RULES.find(([re]) => re.test(category))
  return {
    icon: iconRule ? iconRule[1] : 'Tag',
    color: AUTO_PALETTE[hashString(category || '其他') % AUTO_PALETTE.length],
  }
}

// 用户/AI 自建分类首次出现即落盘：同词两次同色，不跳变；SSR 安全（服务端直接返回计算值，不读写 localStorage）
export function assignAutoStyle(category: string) {
  const name = (category || '').trim()
  if (!name) return { icon: 'DotsThree', color: CATEGORY_PALETTE[0] }
  try {
    if (typeof localStorage === 'undefined') return autoCategoryStyle(name)
    const all = loadCustomCategoryStyles()
    if (all[name]) return all[name]
    const style = autoCategoryStyle(name)
    saveCustomCategoryStyle(name, style)
    return style
  } catch {
    return autoCategoryStyle(name)
  }
}

// 分类图标候选（settings 页图标选择器用，value 须在 AppIcon 注册表内）
export const ICON_CHOICES: Array<{ value: string; label: string }> = [
  { value: 'CookingPot', label: '餐饮' },
  { value: 'Car', label: '交通' },
  { value: 'ShoppingBag', label: '购物' },
  { value: 'GameController', label: '娱乐' },
  { value: 'Basket', label: '生活' },
  { value: 'House', label: '居住' },
  { value: 'FirstAid', label: '医疗' },
  { value: 'GraduationCap', label: '教育' },
  { value: 'DeviceMobile', label: '通讯' },
  { value: 'Lightning', label: '水电' },
  { value: 'ShieldCheck', label: '保险' },
  { value: 'TrendUp', label: '投资' },
  { value: 'CurrencyCny', label: '工资' },
  { value: 'ChartPieSlice', label: '理财' },
  { value: 'ArrowUUpLeft', label: '退款' },
  { value: 'Cloud', label: '数字服务' },
  { value: 'Swap', label: '划转' },
  { value: 'Gift', label: '人情' },
  { value: 'PiggyBank', label: '储蓄' },
  { value: 'Airplane', label: '出行' },
  { value: 'HandCoins', label: '还款' },
  { value: 'Armchair', label: '家居' },
  { value: 'PawPrint', label: '宠物' },
  { value: 'Tag', label: '通用' },
]

// 生产曾出现的分类种子（含 add.vue/transactions.vue 写死项之外的新词）
export const PRODUCTION_CATEGORY_SEED = [
  '餐饮', '交通', '购物', '投资', '数字服务', '其他',
  '自账户划转', '人情往来', '通讯', '还款', '娱乐', '工资', '住房', '家居',
]

// 已知全量分类：内置键 + 生产种子 + 用户自定义键，去重排序（SSR 安全）
export function getAllKnownCategories(): string[] {
  const set = new Set<string>([
    ...Object.keys(categoryIcons),
    ...PRODUCTION_CATEGORY_SEED,
  ])
  try {
    if (typeof localStorage !== 'undefined') {
      for (const k of Object.keys(loadCustomCategoryStyles())) {
        if (k.trim()) set.add(k.trim())
      }
    }
  } catch {
    // 隐私模式忽略
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

// 用户自定义覆盖：设置页调色后存 localStorage，key 为分类名
const CUSTOM_KEY = 'sb-category-styles'

export function loadCustomCategoryStyles(): Record<string, { icon: string; color: string }> {
  try {
    if (typeof localStorage === 'undefined') return {}
    return JSON.parse(localStorage.getItem(CUSTOM_KEY) || '{}')
  } catch {
    return {}
  }
}

export function saveCustomCategoryStyle(category: string, style: { icon: string; color: string }) {
  try {
    const all = loadCustomCategoryStyles()
    all[category] = style
    localStorage.setItem(CUSTOM_KEY, JSON.stringify(all))
  } catch {
    // 隐私模式忽略
  }
}

export function resetCustomCategoryStyle(category: string) {
  try {
    const all = loadCustomCategoryStyles()
    delete all[category]
    localStorage.setItem(CUSTOM_KEY, JSON.stringify(all))
  } catch {
    // 隐私模式忽略
  }
}

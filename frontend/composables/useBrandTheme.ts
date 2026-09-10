/**
 * 品牌 + 明暗主题：三套气质 × 深浅同源 = 6 套皮。
 * brand: ink（纸墨侘寂）| linear（冷峻精密）| cozy（暖绒生活）
 * theme: light | dark（沿用 sb-theme，与旧 data-theme 双写兼容）
 * 驱动：html[data-brand][data-theme] + .dark class（Nuxt UI 用 .dark）
 */
export type Brand = 'ink' | 'linear' | 'cozy' | 'neu'
export type Theme = 'light' | 'dark'

export const BRANDS: { id: Brand; label: string; hint: string }[] = [
  { id: 'ink', label: '纸墨', hint: '东方文人，朱砂点睛' },
  { id: 'linear', label: '冷峻', hint: '精密工具，靛蓝一线' },
  { id: 'cozy', label: '暖绒', hint: '生活气息，陶土暖阳' },
  { id: 'neu', label: '新拟物', hint: '浮雕柔光，软硬兼施' },
]

/** 品牌 → Nuxt UI 调色（需 50-950 全阶，用 Tailwind 内置色） */
export const BRAND_UI_COLORS: Record<Brand, { primary: string; neutral: string }> = {
  ink: { primary: 'red', neutral: 'stone' },
  linear: { primary: 'indigo', neutral: 'zinc' },
  cozy: { primary: 'orange', neutral: 'stone' },
  neu: { primary: 'slate', neutral: 'slate' },
}

const BRAND_KEY = 'sb-brand'

export function useBrandTheme() {
  const brand = ref<Brand>('ink')
  const theme = ref<Theme>('light')

  const applyAll = (b: Brand, t: Theme) => {
    brand.value = b
    theme.value = t
    if (import.meta.client) {
      const h = document.documentElement
      h.setAttribute('data-brand', b)
      h.setAttribute('data-theme', t)
      h.classList.toggle('dark', t === 'dark')
      // Nuxt UI 运行时换色（app.config.ui.colors 响应式，无需 rebuild）
      try {
        const appConfig = useAppConfig() as unknown as {
          ui?: { colors?: { primary?: string; neutral?: string } }
        }
        if (appConfig.ui?.colors) {
          appConfig.ui.colors.primary = BRAND_UI_COLORS[b].primary
          appConfig.ui.colors.neutral = BRAND_UI_COLORS[b].neutral
        }
      } catch {
        // SSR/异常时忽略，靠 CSS 变量兜底
      }
      try {
        localStorage.setItem(BRAND_KEY, b)
        localStorage.setItem('sb-theme', t)
      } catch {
        // 隐私模式忽略
      }
    }
  }

  const setBrand = (b: Brand) => applyAll(b, theme.value)
  const apply = (t: Theme) => applyAll(brand.value, t)
  const toggle = () => apply(theme.value === 'light' ? 'dark' : 'light')

  if (import.meta.client) {
    const h = document.documentElement
    const b = h.getAttribute('data-brand')
    if (b === 'ink' || b === 'linear' || b === 'cozy' || b === 'neu') brand.value = b
    theme.value = h.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
    // 补一次（防闪脚本与模块 hydration 之间状态漂移）
    applyAll(brand.value, theme.value)
  }

  return { brand, theme, setBrand, apply, toggle, brands: BRANDS }
}

/** 旧 useTheme 的兼容出口：老页面不改也能跑 */
export function useTheme() {
  const { theme, apply, toggle } = useBrandTheme()
  return { theme, apply, toggle }
}

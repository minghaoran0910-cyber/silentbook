/** 主题切换：localStorage 持久化 + <html data-theme> 驱动（见 assets/css/main.css） */
export function useTheme() {
  const theme = ref<'light' | 'dark'>('light')

  const apply = (t: 'light' | 'dark') => {
    theme.value = t
    if (import.meta.client) {
      document.documentElement.setAttribute('data-theme', t)
      try {
        localStorage.setItem('sb-theme', t)
      } catch {
        // 隐私模式忽略
      }
    }
  }

  const toggle = () => apply(theme.value === 'light' ? 'dark' : 'light')

  if (import.meta.client) {
    const current =
      document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light'
    theme.value = current
  }

  return { theme, apply, toggle }
}

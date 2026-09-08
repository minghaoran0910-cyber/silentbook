/** 首页 stat 数字 count-up：整数/金额两种格式。
 * - transform/opacity 以外不用，纯文本值变化；时长 800ms，easeOutCubic。
 * - prefers-reduced-motion 下直接显示终值；SSR 下直接渲染终值防 hydration 错位。
 */
import { ref, watch, onMounted } from 'vue'

export type CountUpFormat = 'money' | 'int'

export function useCountUp(
  target: () => number,
  format: CountUpFormat = 'money',
  formatMoney?: (v: number) => string,
  duration = 800,
) {
  const formatValue = (v: number) => {
    if (format === 'int') return String(Math.round(v))
    return formatMoney ? formatMoney(v) : `¥${v.toFixed(2)}`
  }

  const display = ref(formatValue(target()))
  let raf = 0

  const reducedMotion = () =>
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches

  const animate = (to: number) => {
    cancelAnimationFrame(raf)
    if (reducedMotion()) {
      display.value = formatValue(to)
      return
    }
    const from = 0
    const start = performance.now()
    const tick = (now: number) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      display.value = formatValue(from + (to - from) * eased)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
  }

  onMounted(() => animate(target()))
  watch(target, (v) => animate(v))

  return { display }
}

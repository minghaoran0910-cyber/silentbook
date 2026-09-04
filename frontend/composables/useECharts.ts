/** echarts 统一出口：主题跟随（浅/深）、自适应宽度、卸载释放。
 * 用法：
 *   const { el, render } = useECharts()
 *   watch(data, () => render((p) => ({...option using p...})), { immediate: true })
 *   <div ref="el" class="chart-box"></div>
 */
import { ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import * as echarts from 'echarts'

export interface ChartPalette {
  dark: boolean
  text: string
  subtext: string
  border: string
  accent: string
  success: string
  danger: string
  bg: string
}

export function chartPalette(dark: boolean): ChartPalette {
  return dark
    ? {
        dark,
        text: '#E6EDF3',
        subtext: '#8B98A9',
        border: '#232C38',
        accent: '#2DD4BF',
        success: '#4ADE80',
        danger: '#F87171',
        bg: '#11161D',
      }
    : {
        dark,
        text: '#0F172A',
        subtext: '#64748B',
        border: '#E2E8F0',
        accent: '#0F766E',
        success: '#15803D',
        danger: '#B91C1C',
        bg: '#FFFFFF',
      }
}

export function axisCommon(p: ChartPalette) {
  return {
    axisLine: { lineStyle: { color: p.border } },
    axisTick: { show: false },
    axisLabel: { color: p.subtext, fontSize: 11 },
    splitLine: { lineStyle: { color: p.border, type: 'dashed' as const } },
  }
}

export function tooltipCommon(p: ChartPalette) {
  return {
    trigger: 'axis' as const,
    backgroundColor: p.bg,
    borderColor: p.border,
    textStyle: { color: p.text, fontSize: 12 },
    axisPointer: { type: 'shadow' as const },
  }
}

export function useECharts() {
  const el = ref<HTMLElement | null>(null)
  let chart: echarts.ECharts | null = null
  let lastFactory: ((p: ChartPalette) => echarts.EChartsOption) | null = null
  let mo: MutationObserver | null = null
  let ro: ResizeObserver | null = null

  const isDark = () =>
    typeof document !== 'undefined' &&
    document.documentElement.getAttribute('data-theme') === 'dark'

  const doRender = () => {
    if (!el.value || !lastFactory) return
    if (!chart) chart = echarts.init(el.value)
    chart.setOption(lastFactory(chartPalette(isDark())), { notMerge: true })
  }

  function render(factory: (p: ChartPalette) => echarts.EChartsOption) {
    lastFactory = factory
    if (el.value) {
      doRender()
    } else {
      // 数据先于 v-if 的 DOM 到达（如 v-if="list.length" 包着图表 div）：
      // 等本轮 DOM 更新完再画一次
      nextTick(() => doRender())
    }
  }

  // div 因 v-if/tab 切换后挂载（如切到年报 tab）：有缓存 option 就直接画
  watch(el, (node) => {
    if (node) doRender()
  })

  onMounted(() => {
    doRender()
    if (typeof MutationObserver !== 'undefined') {
      mo = new MutationObserver(() => doRender())
      mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    }
    if (typeof ResizeObserver !== 'undefined' && el.value) {
      ro = new ResizeObserver(() => chart?.resize())
      ro.observe(el.value)
    }
  })

  onBeforeUnmount(() => {
    mo?.disconnect()
    ro?.disconnect()
    chart?.dispose()
    chart = null
  })

  return { el, render }
}

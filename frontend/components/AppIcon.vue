<!-- 统一图标出口：Phosphor 单家族、描边 1.8、颜色由调用方按分类传入 -->
<template>
  <component
    :is="component"
    :size="px"
    :color="color"
    weight="regular"
    aria-hidden="true"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import {
  PhMoney,
  PhPiggyBank,
  PhTrendUp,
  PhChartLine,
  PhReceipt,
  PhHouse,
  PhHouseLine,
  PhCoins,
  PhPackage,
  PhHandCoins,
  PhCreditCard,
  PhBank,
  PhCookingPot,
  PhCar,
  PhShoppingBag,
  PhGameController,
  PhBasket,
  PhDeviceMobile,
  PhFirstAid,
  PhGraduationCap,
  PhArrowsLeftRight,
  PhWallet,
  PhCurrencyCny,
  PhChartPieSlice,
  PhArrowUUpLeft,
  PhDotsThree,
  PhLightning,
  PhShieldCheck,
  PhBookOpen,
  PhEye,
  PhEyeSlash,
  PhPencilSimple,
  PhTrash,
  PhMapPin,
  PhCalendarBlank,
  PhDownloadSimple,
  PhUploadSimple,
  PhFileText,
  PhMagnifyingGlass,
  PhFloppyDisk,
  PhPlugsConnected,
  PhCheck,
  PhX,
  PhWarning,
  PhInfo,
  PhPlus,
  PhRobot,
  PhArrowClockwise,
} from '@phosphor-icons/vue'

const props = withDefaults(
  defineProps<{ icon?: string; color?: string; size?: number | string }>(),
  { icon: 'DotsThree', color: 'currentColor', size: 18 }
)

const registry: Record<string, unknown> = {
  Money: PhMoney,
  PiggyBank: PhPiggyBank,
  TrendUp: PhTrendUp,
  ChartLine: PhChartLine,
  Receipt: PhReceipt,
  House: PhHouse,
  HouseLine: PhHouseLine,
  Coins: PhCoins,
  Package: PhPackage,
  HandCoins: PhHandCoins,
  CreditCard: PhCreditCard,
  Bank: PhBank,
  CookingPot: PhCookingPot,
  Car: PhCar,
  ShoppingBag: PhShoppingBag,
  GameController: PhGameController,
  Basket: PhBasket,
  DeviceMobile: PhDeviceMobile,
  FirstAid: PhFirstAid,
  GraduationCap: PhGraduationCap,
  ArrowsLeftRight: PhArrowsLeftRight,
  Wallet: PhWallet,
  CurrencyCny: PhCurrencyCny,
  ChartPieSlice: PhChartPieSlice,
  ArrowUUpLeft: PhArrowUUpLeft,
  DotsThree: PhDotsThree,
  Lightning: PhLightning,
  ShieldCheck: PhShieldCheck,
  BookOpen: PhBookOpen,
  Eye: PhEye,
  EyeSlash: PhEyeSlash,
  PencilSimple: PhPencilSimple,
  Trash: PhTrash,
  MapPin: PhMapPin,
  CalendarBlank: PhCalendarBlank,
  DownloadSimple: PhDownloadSimple,
  UploadSimple: PhUploadSimple,
  FileText: PhFileText,
  MagnifyingGlass: PhMagnifyingGlass,
  FloppyDisk: PhFloppyDisk,
  PlugsConnected: PhPlugsConnected,
  Check: PhCheck,
  X: PhX,
  Warning: PhWarning,
  Info: PhInfo,
  Plus: PhPlus,
  Robot: PhRobot,
  ArrowClockwise: PhArrowClockwise,
}

const component = computed(() => registry[props.icon] || PhDotsThree)
const px = computed(() =>
  typeof props.size === 'number' ? `${props.size}px` : props.size
)
</script>

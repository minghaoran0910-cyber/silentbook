<!-- 分类字形：有图标显示图标，无图标显示分类首字（告别满屏灰点点） -->
<template>
  <AppIcon
    v-if="glyph.kind === 'icon'"
    :icon="glyph.icon"
    :color="glyph.color"
    :size="size"
  />
  <span
    v-else
    class="cat-char"
    :style="{ color: glyph.color, fontSize: `calc(${px} * 0.78)` }"
    aria-hidden="true"
  >{{ glyph.char }}</span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import { categoryGlyph } from '~/utils/icons'

const props = withDefaults(
  defineProps<{ category: string; size?: number | string }>(),
  { category: '其他', size: 20 }
)

const px = computed(() => (typeof props.size === 'number' ? `${props.size}px` : props.size))
const glyph = computed(() => categoryGlyph(props.category))
</script>

<style scoped>
.cat-char {
  font-weight: 800;
  line-height: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
</style>

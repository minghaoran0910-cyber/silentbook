<template>
  <div class="layout">
    <main class="main-content">
      <slot />
    </main>
  </div>
</template>

<script setup>
</script>

<style scoped>
.layout {
  min-height: 100vh;
}

.main-content {
  min-height: 100vh;
}
</style>

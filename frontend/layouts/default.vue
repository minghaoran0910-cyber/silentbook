<template>
  <div class="layout">
    <NavBar />
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
  display: flex;
  flex-direction: column;
}

.main-content {
  flex: 1;
  padding: 2rem;
}

@media (max-width: 640px) {
  .main-content {
    padding: 1rem;
  }
}
</style>

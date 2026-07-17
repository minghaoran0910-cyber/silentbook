<template>
  <nav class="navbar">
    <div class="navbar-inner">
      <NuxtLink to="/" class="brand">
        <span class="brand-icon">◉</span>
        <span class="brand-text">SilentBook</span>
      </NuxtLink>

      <div class="nav-links">
        <NuxtLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="nav-link"
          active-class="active"
        >
          <span class="nav-icon">{{ link.icon }}</span>
          <span class="nav-label">{{ link.label }}</span>
        </NuxtLink>
      </div>

      <div class="nav-right">
        <NuxtLink to="/settings" class="icon-btn" title="设置" aria-label="打开设置">⚙</NuxtLink>
      </div>
    </div>
  </nav>
</template>

<script setup>
const links = [
  { to: '/', label: '总览', icon: '◈' },
  { to: '/assets', label: '资产', icon: '◈' },
  { to: '/investments', label: '投资', icon: '📈' },
  { to: '/goals', label: '目标', icon: '◎' },
  { to: '/transactions', label: '交易', icon: '⇅' },
  { to: '/analysis', label: '分析', icon: '◐' },
  { to: '/settings', label: '设置', icon: '⚙' }
]
</script>

<style scoped>
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
  backdrop-filter: blur(12px);
}

.navbar-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  height: 56px;
  padding: 0 1.5rem;
  gap: 2rem;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
  color: var(--text-primary);
  font-weight: 600;
  font-size: 1.1rem;
  flex-shrink: 0;
}

.brand-icon {
  color: var(--accent);
  font-size: 1.3rem;
}

.nav-links {
  display: flex;
  gap: 0.25rem;
  flex: 1;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.4rem 0.9rem;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.9rem;
  font-weight: 500;
  transition: all 0.15s;
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-tertiary, rgba(255,255,255,0.05));
  text-decoration: none;
}

.nav-link.active {
  color: var(--accent);
  background: var(--accent-glow);
}

.nav-icon {
  font-size: 1rem;
}

.nav-right {
  display: flex;
  gap: 0.5rem;
  flex-shrink: 0;
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 1.1rem;
  transition: all 0.15s;
}

.icon-btn:hover {
  background: var(--bg-tertiary, rgba(255,255,255,0.05));
  color: var(--text-primary);
}

@media (max-width: 640px) {
  .navbar-inner {
    padding: 0 1rem;
    gap: 1rem;
  }
  .nav-label {
    display: none;
  }
  .nav-link {
    padding: 0.4rem 0.6rem;
  }
}
</style>

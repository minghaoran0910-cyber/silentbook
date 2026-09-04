<template>
  <nav class="navbar">
    <div class="navbar-inner">
      <NuxtLink to="/" class="brand">
        <span class="brand-mark" aria-hidden="true"></span>
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
          <span class="nav-label">{{ link.label }}</span>
        </NuxtLink>
      </div>

      <div class="nav-right">
        <button
          class="icon-btn"
          :title="theme === 'light' ? '切换深色' : '切换浅色'"
          :aria-label="theme === 'light' ? '切换深色' : '切换浅色'"
          @click="toggle"
        >
          <svg v-if="theme === 'light'" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
          </svg>
          <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
          </svg>
        </button>
        <NuxtLink to="/settings" class="icon-btn" title="设置" aria-label="打开设置">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1.03 1.56V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1.03-1.56 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.56-1.03H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.65 8.9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.54a1.7 1.7 0 0 0 1.03-1.56V3a2 2 0 1 1 4 0v.09c0 .68.4 1.3 1.03 1.56.6.25 1.3.11 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.7 1.7 0 0 0-.34 1.87c.25.6.88 1.03 1.56 1.03H21a2 2 0 1 1 0 4h-.09c-.68 0-1.3.4-1.51 1.03z" />
          </svg>
        </NuxtLink>
      </div>
    </div>
  </nav>
</template>

<script setup>
import { useTheme } from '~/composables/useTheme'

const { theme, toggle } = useTheme()

const links = [
  { to: '/', label: '总览' },
  { to: '/transactions', label: '交易' },
  { to: '/assets', label: '资产' },
  { to: '/investments', label: '投资' },
  { to: '/goals', label: '目标' },
  { to: '/analysis', label: '分析' },
  { to: '/reports', label: '报表' },
]
</script>

<style scoped>
.navbar {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--bg-secondary);
  border-bottom: 1px solid var(--border);
}

.navbar-inner {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  height: 60px;
  padding: 0 1.5rem;
  gap: 1.5rem;
}

.brand {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  text-decoration: none;
  color: var(--text-primary);
  font-weight: 650;
  font-size: 1.05rem;
  letter-spacing: -0.01em;
  flex-shrink: 0;
}

.brand-mark {
  width: 14px;
  height: 14px;
  border-radius: 4px;
  background: var(--accent);
  flex-shrink: 0;
}

.nav-links {
  display: flex;
  gap: 0.15rem;
  flex: 1;
  overflow-x: auto;
  scrollbar-width: none;
}

.nav-links::-webkit-scrollbar {
  display: none;
}

.nav-link {
  padding: 0.45rem 0.85rem;
  border-radius: var(--radius-sm);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 0.9rem;
  font-weight: 500;
  white-space: nowrap;
  transition: color 0.15s, background-color 0.15s;
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-tertiary);
  text-decoration: none;
}

.nav-link.active {
  color: var(--accent);
  background: var(--accent-soft);
}

.nav-right {
  display: flex;
  gap: 0.35rem;
  flex-shrink: 0;
  align-items: center;
}

.icon-btn {
  width: 36px;
  height: 36px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.15s;
  text-decoration: none;
}

.icon-btn:hover {
  background: var(--bg-tertiary);
  color: var(--text-primary);
  border-color: var(--border);
}

@media (max-width: 720px) {
  .navbar-inner {
    padding: 0 1rem;
    gap: 0.75rem;
  }

  .brand-text {
    display: none;
  }

  .nav-link {
    padding: 0.45rem 0.6rem;
    font-size: 0.85rem;
  }
}
</style>

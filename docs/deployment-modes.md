# SilentBook 部署模式

## 三种部署模式

### 1. 本地模式（推荐新手）
适合：没有服务器、想快速体验的用户

```bash
docker-compose up -d
```

所有服务都在本地运行，数据存在本地。

### 2. 混合模式（推荐进阶用户）
适合：有服务器、但希望数据不出门的用户

**服务器部署：**
- 前端（Nuxt 3）
- 后端 API（FastAPI）

**本地部署：**
- 数据库（PostgreSQL）
- Agent 引擎

**配置：**
```yaml
# docker-compose.server.yml
services:
  frontend: ...
  backend:
    environment:
      - DATABASE_URL=postgresql://user:pass@LOCAL_IP:5432/silentbook
      - AGENT_API_URL=http://LOCAL_IP:5000
```

### 3. 云端模式
适合：想随时随地访问的用户

所有服务部署在服务器，数据在云端。

## 实现方案

### 配置文件分离
- `docker-compose.yml` — 本地模式（默认）
- `docker-compose.server.yml` — 混合模式（前端+后端）
- `docker-compose.local.yml` — 混合模式（数据库+Agent）
- `docker-compose.cloud.yml` — 云端模式

### 环境变量
```bash
# .env.example
DATABASE_URL=postgresql://user:pass@localhost:5432/silentbook
AGENT_API_URL=http://localhost:5000
API_BASE_URL=http://localhost:8000
```

### 文档
README 中说明三种模式的区别和部署步骤。

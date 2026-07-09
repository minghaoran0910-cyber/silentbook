# 部署指南

## 三种部署模式

### 1. 本地模式（推荐新手）

所有服务在本地运行，数据不出门。

```bash
git clone https://github.com/minghaoran0910-cyber/silentbook.git
cd silentbook
cp .env.example .env
# 编辑 .env，填入 API Key
docker-compose up -d
```

访问：
- 前端: http://localhost:3000
- 后端 API: http://localhost:8000
- Agent: http://localhost:5000
- 通知解析器: http://localhost:6000

### 2. 混合模式（推荐进阶）

服务器部署前端+后端，本地部署数据库+Agent。

```bash
# 服务器
docker-compose -f docker-compose.server.yml up -d

# 本地
docker-compose -f docker-compose.local.yml up -d
```

### 3. 云端模式

所有服务部署在云端。

```bash
docker-compose up -d
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DASHSCOPE_API_KEY` | - | 百炼 API Key |
| `SILENTBOOK_MODE` | auto | 分析模式: local/openclaw/auto |
| `OPENCLAW_GATEWAY_URL` | http://localhost:18789 | OpenClaw Gateway 地址 |
| `MODEL_NAME` | aliyun/glm-5.2 | 本地 LLM 模型名 |
| `ABNORMAL_THRESHOLD` | 500 | 异常消费阈值（元） |
| `RATE_LIMIT_REQUESTS` | 100 | API 限流（请求/分钟） |
| `ALLOWED_ORIGINS` | http://localhost:3000 | CORS 允许来源 |

## API 端点

### 交易管理
- `GET /transactions` — 列表（支持筛选）
- `POST /transactions` — 创建
- `PUT /transactions/{id}` — 更新
- `DELETE /transactions/{id}` — 删除

### 统计报表
- `GET /stats/dashboard` — 仪表盘
- `GET /stats/trend` — 消费趋势
- `GET /stats/monthly` — 月报
- `GET /stats/daily` — 日报
- `GET /stats/weekly` — 周报
- `GET /stats/yearly` — 年报
- `GET /stats/asset-curve` — 资产变化曲线

### 通知解析
- `POST /parse` — 解析单条通知
- `POST /webhook/notify` — Webhook 接入（自动解析+异常检测）
- `POST /webhook/notify/batch` — 批量接入

### AI 分析
- `POST /analyze` — 运行 AI 分析
- `GET /analysis/latest` — 最新分析结果
- `GET /analysis/history` — 历史分析列表

### 资产管理
- `GET /assets` — 资产列表
- `POST /assets` — 添加资产
- `PUT /assets/{id}` — 更新
- `DELETE /assets/{id}` — 删除

### 负债管理
- `GET /liabilities` — 负债列表
- `POST /liabilities` — 添加
- `PUT /liabilities/{id}` — 更新
- `DELETE /liabilities/{id}` — 删除

### 预算管理
- `GET /budgets` — 预算列表（含使用率）
- `POST /budgets` — 创建/更新预算
- `DELETE /budgets/{category}` — 删除

### 数据导入导出
- `GET /export/csv` — 导出 CSV
- `POST /import/csv` — 导入 CSV

### 用户认证
- `POST /auth/setup` — 设置密码
- `POST /auth/verify` — 验证密码

### 设置
- `GET /settings` — 获取设置
- `PUT /settings` — 更新设置
- `GET /settings/sources` — 通知源配置
- `PUT /settings/sources` — 更新通知源
- `GET /settings/agents` — Agent 配置
- `PUT /settings/agents/{id}` — 更新 Agent

### 调度器
- `GET /scheduler/status` — 调度器状态
- `POST /scheduler/trigger/{job_id}` — 手动触发

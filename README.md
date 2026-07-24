# SilentBook

> 财务自由，不是终点，是每一步的选择。

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-3776ab.svg)](https://www.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688.svg)](https://fastapi.tiangolo.com)
[![Vue](https://img.shields.io/badge/Vue-3-42b883.svg)](https://vuejs.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ed.svg)](https://www.docker.com)

**全自动无感记账 + AI Agent 协同分析。**

银行和支付通知自动解析入账，无需手动分类；多个 AI Agent 各司其职，持续分析你的消费、投资和财务状况。数据完全属于你，本地部署，不出门。

<!-- TODO: 替换为脱敏后的真实截图 -->
<!-- ![SilentBook Dashboard](docs/assets/screenshot-dashboard.png) -->

---

## ✨ 特性

- 🤖 **无感记账** — 银行/支付通知自动解析入账，覆盖招商银行、工商银行、建设银行、支付宝、微信支付
- 🧠 **多 Agent 协同分析** — 可配置多个 AI Agent（消费分析、投资分析、综合建议），各司其职，独立运行
- 🔐 **数据自主可控** — 本地部署，数据不出门；JWT 认证 + 多租户隔离 + API 限流 + 加密备份
- 🎨 **深色主题** — 电影质感，安静克制，响应式设计适配手机/平板/电脑
- 🐳 **一键部署** — Docker Compose 一条命令拉起全部服务
- 📊 **数据可视化** — 消费趋势、资产曲线、分类饼图、收支对比
- 📅 **自动报表** — 日报/周报/月报/年报，财务全景一目了然
- 🔔 **多渠道通知** — Webhook 接收 + 手动粘贴 + 邮件转发，解析结果实时推送

---

## 🏗️ 架构

```
┌─────────────────────────────────────────────────────────┐
│                      SilentBook                          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ Frontend │  │ Backend  │  │  Agent   │  │ Parser  │ │
│  │ Nuxt 3   │→ │ FastAPI  │→ │ Engine   │  │ Service │ │
│  │ Vue 3    │  │          │  │ (AI分析) │  │(通知解析)│ │
│  └──────────┘  └────┬─────┘  └──────────┘  └─────────┘ │
│                     │                                    │
│              ┌──────┴──────┐                             │
│              │             │                             │
│         ┌────▼────┐   ┌────▼────┐                       │
│         │PostgreSQL│   │  Redis  │                       │
│         │  数据存储 │   │ 限流缓存 │                       │
│         └─────────┘   └─────────┘                       │
└─────────────────────────────────────────────────────────┘
```

| 服务 | 技术 | 端口 | 职责 |
|------|------|------|------|
| Frontend | Nuxt 3 / Vue 3 | 3000 | Web 界面，深色主题，响应式 |
| Backend | FastAPI / SQLAlchemy | 8000 | 核心 API，认证，CRUD，定时任务 |
| Agent | Python / LLM | 5000 | AI 分析引擎，支持本地 LLM 或 OpenClaw |
| Parser | Python | 6000 | 通知解析，5 大平台自动识别 |
| Database | PostgreSQL 15 | 5432 | 持久化存储 |
| Cache | Redis 7 | 6379 | API 限流，会话缓存 |

---

## 🚀 快速开始

### 前置要求

- [Docker](https://docs.docker.com/get-docker/) 和 Docker Compose
- 一个 LLM API Key（阿里云百炼 / OpenAI 兼容接口均可）

### 三步启动

```bash
# 1. 克隆项目
git clone https://github.com/minghaoran0910-cyber/silentbook.git
cd silentbook

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 DASHSCOPE_API_KEY（或你的 LLM Key）
# 生产环境务必修改 JWT_SECRET 和 BACKUP_ENCRYPTION_KEY

# 3. 一键启动
docker compose up -d
```

启动后访问：

| 服务 | 地址 |
|------|------|
| 🌐 前端界面 | http://localhost:3000 |
| 🔧 后端 API | http://localhost:8000 |
| 🤖 Agent 引擎 | http://localhost:5000 |
| 📥 通知解析器 | http://localhost:6000 |

> 首次启动需要构建镜像，约 2-5 分钟。后续启动秒级。

详细配置和高级部署见 [docs/quickstart.md](docs/quickstart.md)。

---

## 🎯 部署模式

SilentBook 支持三种部署模式，适配不同场景：

### 1. 本地模式（默认）

所有服务运行在本地。适合个人使用、注重隐私、不想数据出门。

```bash
docker compose up -d
```

### 2. 混合模式

- **服务器**：前端 + 后端（随时可访问）
- **本地**：数据库 + Agent（数据不出门）

适合有服务器但希望敏感数据留在本地的用户。

```bash
# 服务器端
docker compose -f docker-compose.server.yml up -d

# 本地端
docker compose -f docker-compose.local.yml up -d
```

### 3. 云端模式

所有服务部署在云端 VPS。适合多设备访问、团队共享。

> ⚠️ 云端部署务必配置 HTTPS、强密钥、防火墙规则。

---

## 🔐 安全

SilentBook 处理的是你的财务数据，安全是底线：

- **JWT 认证** — 所有 API 需登录，token 通过 HttpOnly Cookie 下发，防 XSS 窃取
- **多租户隔离** — 数据库层面的行级隔离，用户之间数据完全不可见
- **API 限流** — Redis 滑动窗口限流，防暴力破解和滥用
- **加密备份** — 数据库备份使用 Fernet 对称加密，密钥不入库
- **Webhook 签名** — 通知推送接口使用 HMAC-SHA256 签名 + 幂等校验
- **生产加固** — 生产环境自动启用安全响应头（CSP / HSTS / X-Frame-Options）

> 生产环境必须设置：`JWT_SECRET`（随机 ≥32 字符）、`WEBHOOK_SECRET`、`BACKUP_ENCRYPTION_KEY`。
> 生成方式：`openssl rand -hex 32`

---

## 📂 项目结构

```
silentbook/
├── frontend/              # Nuxt 3 / Vue 3 前端
│   ├── pages/             #   页面（首页/交易/资产/分析/设置）
│   ├── layouts/           #   布局（深色主题）
│   └── components/        #   组件
├── backend/               # FastAPI 后端
│   └── app/
│       ├── main.py        #   应用入口 + 中间件
│       ├── auth.py        #   认证（JWT / 密码重置）
│       ├── database.py    #   数据模型 + 多租户隔离
│       └── tenant.py      #   租户上下文
├── agent/                 # AI Agent 分析引擎
│   └── app/
├── notification-parser/   # 通知解析服务
│   └── app/
├── docs/                  # 文档
│   ├── quickstart.md      #   详细部署指南
│   ├── deployment.md      #   部署模式说明
│   └── contributing.md    #   贡献指南
├── docker-compose.yml          # 本地模式
├── docker-compose.server.yml   # 混合模式（服务器端）
├── docker-compose.local.yml    # 混合模式（本地端）
├── .env.example                # 环境变量模板
└── ROADMAP.md                  # 开发路线图
```

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 前端 | Nuxt 3, Vue 3, TypeScript |
| 后端 | FastAPI, SQLAlchemy 2.0, Pydantic 2 |
| 数据库 | PostgreSQL 15 |
| 缓存 | Redis 7 |
| AI | 阿里云百炼 / OpenAI 兼容接口 / OpenClaw Agent |
| 部署 | Docker Compose |
| 认证 | JWT (PyJWT) + bcrypt |

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request。

- 🐛 发现 Bug → [提 Issue](https://github.com/minghaoran0910-cyber/silentbook/issues)
- 💡 功能建议 → [提 Issue](https://github.com/minghaoran0910-cyber/silentbook/issues) 标记 `enhancement`
- 🔧 代码贡献 → Fork → 新建分支 → 提 PR

详见 [docs/contributing.md](docs/contributing.md)。

---

## 📄 License

[MIT](LICENSE) — 自由使用、修改、分发。

---

<p align="center">

**SilentBook** — 让 AI 帮你管钱，而不是帮你花钱。

</p>

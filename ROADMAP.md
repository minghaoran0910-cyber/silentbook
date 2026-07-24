# SilentBook 开发路线图

## ✅ 已完成

### 核心功能
- **通知解析器** — 招商银行、工商银行、建设银行、支付宝、微信支付，5 大平台自动识别
- **后端 API** — 交易/资产/负债 CRUD、仪表盘统计、定时任务
- **前端界面** — 首页、交易、资产、分析、设置、手动记账，深色主题响应式
- **AI 分析引擎** — 多 Agent 协同（消费分析/投资分析/综合建议），支持本地 LLM 和 OpenClaw
- **通知推送** — Webhook 接收 + 手动粘贴 + 邮件转发，解析结果实时推送

### 数据可视化
- 消费趋势图（月度/周度）、资产变化曲线、消费分类饼图、收支对比柱状图
- 自动报表：日报 / 周报 / 月报 / 年报

### 安全
- JWT 认证（HttpOnly Cookie）
- 多租户数据隔离（数据库行级）
- Redis API 限流
- 数据库加密备份（Fernet）
- Webhook HMAC 签名 + 幂等校验
- 生产安全响应头（CSP / HSTS / X-Frame-Options）

### 部署
- Docker Compose 一键部署（本地 / 混合 / 云端三种模式）
- 端到端部署验证通过

---

## 🚧 进行中

- **桌面端打包** — 评估 Tauri + SQLite 单用户轻量模式（详见下方说明）
- **SQLite 轻量模式** — 单进程运行，无需 PostgreSQL/Redis，降低个人用户部署门槛
- **跨平台一键安装脚本** — Linux / macOS / Windows 环境自动检测 + 配置生成

---

## 📋 规划中

- **更多通知来源** — 交通银行、浦发银行、美团、京东等
- **预算预警** — 分类预算设置 + 超支实时提醒
- **多币种支持** — 汇率自动换算
- **数据导入/导出** — CSV / Excel / OFX
- **PWA 优化** — 离线缓存、手势操作
- **社区** — 插件系统、自定义解析规则、Agent 市场

---

## 💡 关于桌面端

SilentBook 当前是 6 服务的分布式架构（Frontend + Backend + Agent + Parser + PostgreSQL + Redis），天然适合服务器/Docker 部署。

对于个人桌面用户，我们的方向是：
1. **SQLite 单用户模式**（优先）— 去掉 PostgreSQL/Redis 依赖，单进程运行，`pip install` 或单条命令即可启动
2. **Tauri 桌面壳**（后续）— 在 SQLite 模式成熟后，打包为 macOS `.dmg` / Windows `.exe`

> 我们**不**优先做 Electron 套壳——它不解决后端运行问题，且对财务类应用来说，自托管 + 代码透明比闭源可执行文件更值得信任。

---

有想法或建议？欢迎 [提 Issue](https://github.com/minghaoran0910-cyber/silentbook/issues) 讨论。

# SilentBook 安全与架构审查报告

**日期：** 2026-07-24
**方法：** deep-grill（攻击者 + 审计员双视角，逐项自我反驳，查证优先于假设）
**范围：** backend / frontend / agent / notification-parser / 部署配置 / 依赖 / 文档
**提交基线：** a0c5acc（含此前 6 个交付 commit）

---

## 0. 总评

经过此前数轮 deep-grill 修复（CSRF 域名登录、SQLite 跨线程、Nuxt `/api` 代理、Docker Hub 镜像），**运行时 P0 已收敛干净——本轮未发现需要"闭眼立刻修"的运行时 P0 漏洞。**

本轮挖到的均为**架构卫生 / 纵深防御 / 死代码攻击面 / 依赖 / 产品摩擦**类问题，需要权衡或人工 review，不宜擅自改动。下文分级列出，并附"已自我反驳排除的误报"，避免制造恐慌。

---

## 1. 已验证安全的核心防线

### 1.1 认证（backend/app/auth.py）
- 生产强制强 JWT 密钥：默认弱密钥在生产直接 `raise RuntimeError`（auth.py 启动校验）。
- Cookie 为 HttpOnly + `secure`(生产) + `samesite=strict`；生产 token 不放响应 body。
- `dev-reset-password` 生产封堵：`APP_ENV not in (development,dev)` 即 403（auth.py:261-264）。
- `forgot-password` 防用户枚举（不存在也返回相同消息），生产不泄露重置 token（无 SMTP 时只回通用消息）。

### 1.2 多租户数据隔离（backend/app/database.py + main.py）
- **全部 17 个业务数据模型**（Transaction/Asset/Liability/Account/Transfer/AnalysisResult/Position/TradeRecord/FinancialGoal/GoalContribution/RecurringTransaction/SyncLog/BackupRecord/WebhookEvent/AgentConfig/Setting）均继承 `UserOwnedMixin`；仅 `User` 继承 `Base`（正确，User 是被隔离主体）。
- `do_orm_execute` 钩子以 `with_loader_criteria(UserOwnedMixin, user_id==scoped)` 覆盖所有业务表的读/改/删。
- 路由依赖审查（修正 async 识别后的真实结果）：**123 个路由中 110 个 `require_user`，0 个使用可空依赖 `get_current_user`** —— 不存在"应 require 却用可空依赖"的越权读。

### 1.3 Webhook 入站（backend/app/main.py:454-492）
- HMAC-SHA256 签名 + ±300s 时间窗 + `hmac.compare_digest` 防时序攻击 + `event_id` 幂等（唯一索引）。
- **空/弱密钥防护到位**：`not secret or len(secret)<32 or not configured_user_id.isdigit()` 即 503，不会用空密钥签名。
- body 大小上限（默认 1MB）防滥用。

### 1.4 凭据 / PII 卫生
- 全仓扫描：代码区 **0 命中**真实密钥 / 个人手机号 / 邮箱 / 服务器 IP。
- `.env` 未被 git 跟踪，`.gitignore` 含 `.env` 规则。

---

## 2. 待处理项（分级）

### 🟡 P1-A 死代码攻击面：遗留伪认证 + onboarding（前端 0 引用却公开暴露）

后端存在**第二套认证/引导系统**，经 grep 确认**前端无任何调用**（pages/composables/components 零引用 `onboarding|auth/setup|auth/verify|auth/status`），属死代码，但仍公开暴露：

| 端点 | 风险 |
|------|------|
| `POST /auth/setup` | 公开无认证，任何人可覆盖 `Setting` 表中的访问密码（sha256 弱哈希）。当前业务路由不验此密码，危害为污染 + 干扰前端引导态判断 |
| `POST /auth/verify` | 用 **md5(password+time)** 生成无校验意义的 token；密码用 sha256 存 —— 密码学实践错误 |
| `POST /onboarding/init` | 创建 `Asset` 时**未设 user_id**，多租户下违反 NOT NULL → 500（当前被约束挡住，未造成越权写，但属定时炸弹） |
| `GET /onboarding/status` | 因租户钩子强制 `user_id==-1`，count 恒为 0，逻辑恒错 |

**建议：整组删除**（已验证前端 0 引用，删除零功能影响）。

### 🟡 P1-B 纵深防御缺口：`/collaboration/*` 无认证

`/collaboration/moyan/consumption`、`/collaboration/yuanzhan/investment`、`/collaboration/hao-ran-life/markdown` 故意无认证（供墨砚/远瞻子代理调用）。当前靠 backend 端口绑定 `127.0.0.1:8000` + nginx 不转发该路径**间接**挡公网。

**风险：** 若哪天 backend 端口暴露，或新增 `/api/collaboration` 代理，浩然财务数据即裸奔。
**建议：** 加协作专用共享密钥 header 校验（不破坏子代理调用，因它们无用户 JWT）。涉及墨砚/远瞻调用方同步改造，建议排期。

### 🟡 P1-C lite 模式默认 `WEBHOOK_SECRET` 为开源可见弱值

lite compose 默认 webhook secret 是仓库公开字符串。攻击者经 frontend `/api/webhook/notify`（公网可达）用默认密钥即可伪造 webhook 入账（`WEBHOOK_USER_ID` 默认 1 亦公开）。

**建议：** lite compose 默认将 `WEBHOOK_SECRET` 留空 → webhook 自动 503 禁用；需用者在 `.env` 自配。开箱即安全。

### 🟢 P2-A 依赖：frontend svgo 4.0.1（GHSA-2p49-hgcm-8545，npm 标 high）

- 依赖链：`nuxt → @nuxt/vite-builder → cssnano → postcss-svgo → svgo`（**transitive，构建链**）。
- **deep-grill 反驳 npm 评级：** 该 XSS 类漏洞触发点为"处理不可信 SVG"，而 cssnano 仅优化项目自有 CSS/内联 SVG，**不处理用户输入**，实际利用面极低。
- **建议：** 跟随 nuxt 升级自然修复，**不强行 `npm audit fix`**（避免动 cssnano 版本引入构建回归）。如实呈现"npm=high / 实际=低"两种视角。

### 🟢 P2-B 依赖：backend 未自动审计

本地环境无 `pip-audit` / `pip`，本轮未跑成 backend 依赖 CVE 扫描。**不假装查过。**
**待办命令：** `pip install pip-audit && pip-audit -r backend/requirements.txt`

### 🟢 P2-C lite 开箱需先注册（产品摩擦）

lite 单用户场景仍要求"注册账号→登录"。前端不走 onboarding，走标准 JWT 注册/登录，功能可用但不够"无感"。
**可选增强：** lite 首次启动自动建默认用户并下发 cookie（需评估，非必须）。

### 🟢 P2-D README 截图占位未补

`README.md:15-16` 仍为注释占位。建议用隔离栈 demo 数据补真实截图（不碰生产真实数据）。

---

## 3. 已自我反驳排除的误报（审查诚实记录）

1. **"所有路由公开越权"假阳性** —— 首版路由审查脚本未识别 `async def`，致全部 async 路由误标 NONE。修正（async + 括号计数）后真实结果为 110/123 受保护。**未据此误报做任何改动。**
2. **"lite 引导流程断裂"假设** —— 曾怀疑 onboarding 死代码导致 lite 开箱不可用；grep 证实前端不走 onboarding、走标准 JWT 注册登录，**未断裂**。
3. **"webhook 空密钥可伪造"P0 担忧** —— 查证 main.py:456-458 已 503 防护，**降级为已防护**。

---

## 4. 本轮未做"闭眼代码修改"的说明

本轮发现的问题均属"需权衡 / 涉及多方 / 行为变更 / 死代码删除"，没有"确认是 bug 且修复零争议"的项。遵循人工 review 偏好，**不擅自 commit 删除或行为变更**，将决策权交还（见微信汇报的决策清单）。审查报告本身作为留痕提交。

---

*审查人：老油条（deep-grill 自审）*

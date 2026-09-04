# Android 端直推指南（Tasker，无需 Cone 卡）

> iOS 由于系统限制无法监听第三方通知自动转发，iPhone 用户请用
> Cone 智能卡片或 Mac/PC 中继方案（见 README 依赖声明）。
> Android 有 `NotificationListenerService`，Tasker 可直接监听并 POST，
> 全程不经过任何第三方硬件。

## 0. 前提

- Android 8+ 手机一部，安装 Tasker（付费应用）并授予**通知访问权限**
  （系统设置 → 应用 → 特殊应用权限 → 通知使用权 → Tasker）。
- SilentBook 服务地址（局域网可达，如 `http://192.168.31.2:3100`）
  和 `WEBHOOK_SECRET`（服务端 `.env` 里取）。
- HMAC 签名代码见 `docs/tasker-hmac.cjs`（已用 6 组向量对 Python `hmac`
  交叉验证，含中文/长密钥/空输入；Tasker 里原样粘贴函数部分即可）。

## 1. 建 Profile（监听通知）

Tasker → Profiles → `+` → Event → UI → Notification：

- Owner Application：**直接在 Tasker 内点选已安装的银行/支付 App**
  （招行/工行/建行/农行/中行/交行/浦发、支付宝、微信、美团、京东、淘宝），
  不要手填包名（各行各版本包名可能不同，点选最准）。
- Title / Text 留空（服务端 parser 自己过滤分类，非财务通知会回 `filtered`）。
- 通知变量（标题/正文/应用）以 Tasker 内置变量选择器为准
  （通常是事件参数 `%evtprm1/2/3` 或 `%NTITLE/%NTEXT`，版本有差异，
  在 JavaScriptlet/HTTP 动作里点 `</>` 标签图标选取，不要硬背）。

## 2. 建 Task（签名 + POST，二选一按量来）

Task 名如 `SB记账推送`，两个 Action：

**Action 1 — JavaScriptlet**（先声明变量 `SB_SECRET`/`SB_TS`/`SB_BODY`，
`SB_TS` 用 Tasker `%TIMES`，`SB_BODY` 按下面格式拼）：

```json
{"title": "%NTITLE", "body": "%NTEXT", "source": "<按上表填id>", "timestamp": "%DATE %TIME"}
```

> `%NTITLE/%NTEXT` 为触发通知的标题正文；`source` 按 App 包名对照上表填
> （如支付宝填 `alipay`）；时间格式服务端兼容 ISO 与常见格式。
> JavaScriptlet 末尾（`docs/tasker-hmac.cjs` 函数部分粘在前面）：
> `var SB_SIG = 'sha256=' + sb_hmac_sha256(SB_SECRET, SB_TS + '.' + SB_BODY);`

**Action 2 — HTTP Request**：

- Method `POST`，URL `http://<host>:<port>/api/webhook/notify`
  （批量用 `/api/webhook/notify/batch`，body 改数组）。
- Headers：`Content-Type: application/json`、
  `X-Silentbook-Timestamp: %SB_TS`、
  `X-Silentbook-Event-Id: %TIMEMS`（每次唯一，重试会换新值）、
  `X-Silentbook-Signature: %SB_SIG`。
- Body：`%SB_BODY`（**必须与签名时一字不差**，不要让 Tasker 二次转义）。

## 3. 自验（ highway ）

1. 自己转 1 分钱 → Tasker 日志显示 200 且 `status=created`。
2. 同一条重发（换 `TIMEMS`）→ `duplicate`，账不错乱。
3. 发一条微信聊天 → `filtered`（属正常）。
4. 用错 secret 发一条 → 401（证明签名链是真校验）。

## 4. 故障排查

| 现象 | 查哪里 |
|---|---|
| 401 | secret 对不上；签名 body 与 POST body 不一致；手机时间漂移超 5 分钟 |
| 409 | event id 重用了（`%TIMEMS` 正常不会） |
| 503 解析器不可用 | 服务端 parser 容器是否 healthy |
| 收不到通知事件 | Tasker 通知权限被杀后台：锁后台、自启动、省电无限制三件套 |

## 5. 和 Cone 方案的关系

两者是**或**关系：同一条通知只走一条链路，否则靠服务端 `duplicate`
兜底（能兜住，但别故意双推）。iPhone 目前无 Tasker 等价物，
继续用 Cone 卡或 Mac 中继（见 README 依赖声明）。

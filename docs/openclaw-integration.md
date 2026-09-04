# OpenClaw 接入 SilentBook：通知沉淀 + AI 分析

> 读者：OpenClaw Agent（或配置它的人）。目标：把手机通知变成自动记账，
> 并可选用 OpenClaw subagent 做财务分析。

## 1. 链路总览

```
手机通知 → 采集（phone-notifications 插件 / C.one 二选一）
  → OpenClaw 定时任务（过滤 + 签名）
  → POST /webhook/notify 或 /webhook/notify/batch（经站点的 /api 代理也可）
  → Notification Parser（15 家银行/平台，方向判定，分类）
  → 交易入库 + 账户余额联动 + 异常事件驱动分析
```

生产地址示例：`https://<host>/api/webhook/notify`（同源代理，直达后端，无跨域）。

## 2. Webhook 签名（必须完全一致，否则 401）

- Header：`X-Silentbook-Timestamp`（秒级 Unix 时间，±300s）、
  `X-Silentbook-Event-Id`（唯一，重复判 409）、
  `X-Silentbook-Signature`（可带 `sha256=` 前缀）。
- 算法：`HMAC-SHA256(secret, f"{timestamp}." + raw_body_bytes)`，
  **对原始请求体字节签名**，不要重新序列化 JSON（空格/键序不同即验签失败）。
- `secret` = 服务端 `.env` 的 `WEBHOOK_SECRET`（≥32 字符）；
  `WEBHOOK_USER_ID` 指定入账归属用户（该用户必须存在且启用）。
- Body 限制 1MB；batch 单次 ≤100 条，请求体是**数组**（不是 `{"items": [...]}`）。

最小可用示例（Python）：

```python
import hmac, hashlib, json, time, uuid, urllib.request

SECRET = "从服务端 .env 取 WEBHOOK_SECRET"
BASE = "https://<host>/api"

def push(items: list):
    body = json.dumps(items, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    sig = "sha256=" + hmac.new(
        SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(
        BASE + "/webhook/notify/batch", data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-Silentbook-Timestamp": ts,
                 "X-Silentbook-Event-Id": str(uuid.uuid4()),
                 "X-Silentbook-Signature": sig,
                 "User-Agent": "Mozilla/5.0 SilentBookSync/1.0"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())
```

单条把 URL 换成 `/webhook/notify`，body 换成单个对象
`{"title": ..., "body": ..., "source": ..., "timestamp": ...}` 即可。

## 3. 幂等语义（OpenClaw 端必须遵守）

- 整批共用一个 `event_id`：**重试必须换新 event_id**，否则整批 409。
- 换新 event_id 重试：已入库条目逐条返回 `{"status": "duplicate"}`，不会重记。
- 单条错误（解析器挂了 503、缺字段 422）**不炸整批**，
  看 `results[i].status` 逐条处理：`created / duplicate / filtered / skipped / error`。
- 永远不要把同一批通知长期攒着一次性推；建议按天增量 + 本地 checkpoint。

## 4. `source` 标识表（推送端直接传 id，服务端精确优先）

`cmb 招商银行`、`icbc 工商银行`、`ccb 建设银行`、`abc 农业银行`、
`boc 中国银行`、`bocom 交通银行`、`spdb 浦发银行`、`ceb 光大银行`、
`citic 中信银行`、`unionpay 云闪付`、`alipay 支付宝`、
`wechat_pay 微信支付`、`meituan 美团`、`jd 京东`、`taobao 淘宝`。

未知 source 不会炸（走通用金额兜底），但账户会存原文、余额联动跳过，
所以尽量传上表 id。

## 5. AI 分析两种模式

| 模式 | 说明 | 需要配置 |
|------|------|----------|
| `local` | 后端直调 OpenAI 兼容接口（百炼等） | 用户在设置页填 API Base/Key/模型，或 `.env` 的 `DASHSCOPE_API_KEY` |
| `openclaw` | 经 OpenClaw Gateway spawn subagent（墨砚管消费/远瞻管投资） | 容器 `OPENCLAW_GATEWAY_URL`（默认 `http://host.docker.internal:18789`，R4S 等非桌面环境按实际改） |
| `auto`（默认） | 优先 openclaw，失败回退 local | 同上 |

无 Key 时分析接口返回占位提示且**不入库**（历史不被污染）。

OpenClaw Agent 绑定（设置页 → OpenClaw 绑定 → 获取清单 → 绑定）：
对应接口 `GET/POST/DELETE /settings/openclaw-binding`
（旧拼写 `openclaw-bindding` 仍兼容）。

## 6. 定时任务建议（OpenClaw cron 参考）

- 通知沉淀：每小时一次，增量推送（记住上次时间戳），失败换新 event_id 重试。
- 每日分析：SilentBook 自带 20:00 定时分析，无需 OpenClaw 另起。
- 资产同步：SilentBook 自带每日 15:30（收盘后）同步，无需外部触发。

## 7. 故障排查速查

| 现象 | 查哪里 |
|------|--------|
| 401 签名错 | secret 两边是否一致；是否对**原始字节**签名；时间戳是否过期 |
| 409 | event_id 重用了，换新的 |
| 503 Webhook 未配置 | 服务端 `WEBHOOK_SECRET` 空/太短或 `WEBHOOK_USER_ID` 非法 |
| 503 解析器不可用 | notification-parser 容器是否 healthy |
| 入账了但分类是其他 | 提 Issue 附原文（脱敏），加关键词即可 |
| 200 filtered | 非财务通知被过滤，看 `reason`（属正常） |

完整签名算法与样本见 `docs/notification-pipeline.md`。

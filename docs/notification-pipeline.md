# 通知链路配置指南

> SilentBook 的"自动记账"不是凭空工作的——它依赖一条从手机通知到交易入库的完整链路。本文档详细说明每个环节如何配置。

---

## 📡 完整链路

```
📱 手机银行/支付宝/微信 消费通知
    ↓
🃏 Yoooclaw C.one 智能卡片（手机端通知同步服务）
    ↓
🤖 OpenClaw Agent（定时沉淀通知到 SilentBook 服务器）
    ↓
📥 SilentBook /webhook/notify API（HMAC 签名验证）
    ↓
🔍 Notification Parser（识别银行/金额/商户/分类）
    ↓
💰 交易记录自动入库
```

---

## 1️⃣ Yoooclaw C.one 智能卡片

**这是什么：** 一个手机端通知同步服务，负责把手机上的银行/支付通知提取出来，推送给下游系统。

**为什么需要：** 银行 App 的消费通知是推送到手机系统的——SilentBook 运行在服务器端，无法直接读取手机通知。C.one 充当"桥梁"，把手机通知同步出来。

**配置步骤：**
1. 安装 Yoooclaw C.one 智能卡片（详见 [yoooclaw.com](https://yoooclaw.com)）
2. 授权通知读取权限
3. 配置通知转发目标，指向你的 OpenClaw 实例

> ⚠️ C.one 是自动记账的**必要前置条件**。没有它，SilentBook 无法获取手机通知。
>
> 💡 **已验证的本地路径**：手机通知 → OpenClaw `phone-notifications` 插件落盘
> （`~/.openclaw/plugins/phone-notifications/notifications/*.json`）→ 推送脚本严格过滤
> 金融类（银行短信号段/支付宝/微信支付关键词）→ 微信·银行同笔去重 →
> `POST /webhook/notify/batch`。C.one 可视为同类通知源的一种，按本页签名规范推送即可。

---

## 2️⃣ OpenClaw 通知沉淀

**这是什么：** OpenClaw 是一个 AI Agent 运行时。通过定时任务（cron），它从 C.one 读取通知，推送到 SilentBook 的 Webhook API。

**为什么需要：** OpenClaw 负责"沉淀"——它不只是转发通知，还会做初步过滤（非财务通知直接丢弃），并通过 HMAC 签名保证数据安全。

**配置步骤：**

1. 安装 OpenClaw（详见 [docs.openclaw.ai](https://docs.openclaw.ai)）
2. 配置通知沉淀 cron 任务，定时将通知推送到 SilentBook：

```bash
# OpenClaw cron 配置示例
# 每小时沉淀一次通知到 SilentBook
{
  "name": "silentbook-notification-sync",
  "schedule": { "kind": "cron", "expr": "0 * * * *" },
  "payload": {
    "kind": "agentTurn",
    "message": "将最近1小时的手机通知推送到 SilentBook webhook"
  }
}
```

3. 配置 SilentBook Webhook 地址和签名密钥（见下方 Webhook 章节）

---

## 3️⃣ SilentBook Webhook API

SilentBook 通过 `/webhook/notify` 接口接收通知。

### 请求格式

```json
POST /webhook/notify

{
  "title": "招商银行",
  "body": "您尾号1234的储蓄卡消费人民币88.00元，商户：星巴克咖啡",
  "source": "cmb",
  "timestamp": "2026-07-28T15:00:00+08:00"
}
```

> `event_id` 不在 body 里，通过请求头 `X-Silentbook-Event-Id` 传递（用于幂等）。

### HMAC 签名验证

所有 webhook 请求必须携带 HMAC-SHA256 签名，防止伪造。

**必需的请求头：**

| Header | 说明 |
|--------|------|
| `X-Silentbook-Timestamp` | Unix 时间戳（秒），超过 5 分钟的请求会被拒绝 |
| `X-Silentbook-Event-Id` | 唯一事件 ID，用于幂等校验（重复 ID 会被拒绝，`sha256=` 前缀可选） |
| `X-Silentbook-Signature` | HMAC-SHA256 签名，可带 `sha256=` 前缀 |

**签名算法（与后端 `verify_webhook` 及推送脚本严格一致）：**

```python
import hmac, hashlib, time

secret = "你的WEBHOOK_SECRET"  # 在 .env 中配置
body_bytes = b'...'  # 请求体的原始字节（不要重新序列化）
timestamp = str(int(time.time()))

# 签名内容 = timestamp + "." + 原始请求体字节
signature = "sha256=" + hmac.new(
    secret.encode(),
    f"{timestamp}.".encode() + body_bytes,
    hashlib.sha256,
).hexdigest()
```

> ⚠️ 必须对**原始请求体字节**签名，不要 `json.dumps` 重组后再签（空格/键序不同会导致 401）。

**密钥配置：**
- `install.sh` 会自动生成 `WEBHOOK_SECRET`（写入 `.env`）
- 手动部署时，用 `openssl rand -hex 32` 生成
- OpenClaw 端必须配置相同的 secret

### 批量推送

```json
POST /webhook/notify/batch
// 请求体是数组（不是 {"items": [...]}），单次最多 100 条
[
  { "title": "...", "body": "...", "source": "...", "timestamp": "..." },
  { "title": "...", "body": "...", "source": "...", "timestamp": "..." }
]
```

单次最多 100 条。整批共用一套请求头签名；重试请换新的 `X-Silentbook-Event-Id`，否则会被判重（409）。

---

## 4️⃣ Notification Parser 过滤逻辑

收到通知后，SilentBook 会先判断"这是不是财务通知"，非财务通知会被直接丢弃。

### 过滤规则

**会被识别为财务通知的：**
- 包含银行名称（招商银行、工商银行、建设银行等）
- 包含支付平台名（支付宝、微信支付）
- 包含金额关键词（消费、支出、收入、转账、还款等）

**会被过滤掉的：**
- 营销通知（"您有一条优惠消息"）
- 系统通知（"App 已更新"）
- 社交消息（微信聊天、群消息）
- 其他非财务内容

### 支持的银行/平台

| 平台 | 标识 | 识别关键词 |
|------|------|-----------|
| 招商银行 | `cmb` | 招商银行、招行、CMB |
| 工商银行 | `icbc` | 工商银行、工行、ICBC |
| 建设银行 | `ccb` | 建设银行、建行、CCB |
| 农业银行 | `abc` | 农业银行、农行、ABC、金穗 |
| 中国银行 | `boc` | 中国银行、中行、BOC |
| 交通银行 | `bocom` | 交通银行、交行、太平洋卡 |
| 浦发银行 | `spdb` | 浦发银行、浦发、SPDB |
| 光大银行 | `ceb` | 光大银行、光大、CEB、阳光卡 |
| 中信银行 | `citic` | 中信银行、中信、CITIC |
| 云闪付 | `unionpay` | 云闪付、UnionPay、银联 |
| 支付宝 | `alipay` | 支付宝、Alipay |
| 微信支付 | `wechat_pay` | 微信支付、WeChat Pay |
| 美团 | `meituan` | 美团、美团外卖、大众点评 |
| 京东 | `jd` | 京东、JD、白条、京东支付 |
| 淘宝 | `taobao` | 淘宝、天猫、Tmall |

> 推送端 `source` 字段请直接传上表标识（如 `bocom`），服务端精确优先，
> 避免子串误判（`bocom` 含 `boc`，曾把交通银行判成中国银行）。

### 自动分类

解析后的交易会自动归类：

| 分类 | 关键词示例 |
|------|-----------|
| 餐饮 | 美团、饿了么、星巴克、瑞幸、咖啡、外卖 |
| 交通 | 滴滴、地铁、公交、加油、12306 |
| 购物 | 淘宝、京东、拼多多、超市 |
| 娱乐 | 电影、游戏、健身、B站 |
| 生活 | 水电、物业、房租、话费 |
| 医疗 | 医院、药、体检 |
| 投资 | 基金、股票、理财、定投 |

> 💡 如果某条通知被错误过滤或分类错误，可以提 Issue 让我们增加对应的 pattern。

---

## 🔧 故障排查

### 通知没有变成交易？

按以下顺序检查：

1. **C.one 是否正常工作？** — 检查 C.one 是否在同步通知
2. **OpenClaw 是否在推送？** — 检查 OpenClaw cron 是否正常运行
3. **Webhook 是否可达？** — `curl http://localhost:8000/health` 应返回 `{"status":"ok"}`
4. **签名是否正确？** — 检查 401 错误日志，确认 WEBHOOK_SECRET 一致
5. **通知是否被过滤？** — 检查 parser 日志，看通知是否被判定为非财务内容

### 测试 Webhook 连通性

```python
#!/usr/bin/env python3
"""测试 SilentBook webhook 是否正常工作"""
import hmac, hashlib, time, json, httpx

WEBHOOK_URL = "http://localhost:8000/webhook/notify"
SECRET = "***"  # 从 .env 获取

payload = {
    "title": "招商银行",
    "body": "您尾号1234的储蓄卡消费人民币88.00元，商户：星巴克",
    "source": "cmb",
    "timestamp": "2026-07-28T15:00:00+08:00",
}
event_id = f"test-{int(time.time())}"

body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
timestamp = str(int(time.time()))

signature = "sha256=" + hmac.new(
    SECRET.encode(),
    f"{timestamp}.".encode() + body_bytes,
    hashlib.sha256,
).hexdigest()

headers = {
    "X-Silentbook-Timestamp": timestamp,
    "X-Silentbook-Event-Id": event_id,
    "X-Silentbook-Signature": signature,
    "Content-Type": "application/json",
}

resp = httpx.post(WEBHOOK_URL, content=body_bytes, headers=headers)
print(f"状态码: {resp.status_code}")
print(f"响应: {resp.json()}")
```

预期输出：`状态码: 200`，交易自动入库。

---

## 📋 测试通知样本

用以下文本测试 notification-parser 是否能识别你的银行格式：

### 招商银行

```
招商银行通知：您尾号1234的储蓄卡于7月28日消费人民币88.00元，商户：星巴克咖啡，余额12345.67元。
```

**预期解析结果：**
- 金额：88.00
- 分类：餐饮
- 账户：招商银行
- 交易类型：expense

### 工商银行

```
工商银行：您尾号5678的信用卡于2026-07-28 14:30在美团外卖消费人民币32.50元。
```

**预期解析结果：**
- 金额：32.50
- 分类：餐饮
- 账户：工商银行
- 交易类型：expense

### 建设银行

```
建设银行：您尾号9012的账户于07月28日转账支出人民币500.00元，收款方：张三，余额8888.88元。
```

**预期解析结果：**
- 金额：500.00
- 分类：其他
- 账户：建设银行
- 交易类型：expense

### 支付宝

```
支付宝：您在「瑞幸咖啡」扫码付款¥15.00元，交易时间2026-07-28 09:30:00。
```

**预期解析结果：**
- 金额：15.00
- 分类：餐饮
- 账户：支付宝
- 交易类型：expense

### 微信支付

```
微信支付：您在「滴滴出行」消费¥25.80元，付款方式：零钱。
```

**预期解析结果：**
- 金额：25.80
- 分类：交通
- 账户：微信
- 交易类型：expense

### 收入通知

```
招商银行：您尾号1234的储蓄卡收入人民币10000.00元，摘要：工资，余额25000.00元。
```

**预期解析结果：**
- 金额：10000.00
- 分类：其他
- 账户：招商银行
- 交易类型：income

---

**测试方法：**

```bash
# 启动 notification-parser 服务
cd notification-parser
python -m uvicorn app.main:app --reload --port 6000

# 测试招商银行通知
curl -X POST http://localhost:6000/parse \
  -H "Content-Type: application/json" \
  -d '{
    "title": "招商银行通知",
    "body": "您尾号1234的储蓄卡于7月28日消费人民币88.00元，商户：星巴克咖啡，余额12345.67元。",
    "source": "cmb"
  }'
```

如果解析结果与预期不符，欢迎提 Issue 让我们增加对应的 pattern。

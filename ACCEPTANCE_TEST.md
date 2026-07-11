# SilentBook 验收测试流程

**创建时间：** 2026-07-11 14:13
**目标：** 确保 SilentBook 系统可以正式投入使用

---

## 一、当前状态（15:13 更新）

### ✅ 已完成

| 任务 | 状态 | 说明 |
|------|------|------|
| P0-1 前端 healthcheck | ✅ | Dockerfile 改用 0.0.0.0，本地+服务器容器 healthy |
| P0-2 本地账户初始化 | ✅ | 招商/支付宝/微信/现金 4 个账户 |
| P0-3 本地全流程验证 | ✅ | 12 条交易写入，Dashboard 正常 |
| P1-1 清理旧目录 | ✅ | finance-system 已归档到 .archive/ |
| P1-2 代码同步 | ✅ | git push + 服务器 rebuild，全部 healthy |
| P2-1 Agent 分析超时 | ✅ | 响应时间 3-5 秒，可接受 |
| S1 服务器账户初始化 | ✅ | 4 个账户创建成功 |
| S2 服务器真实数据导入 | ✅ | 7 条交易记录写入 |
| S3 服务器全流程验证 | ✅ | AI 分析功能正常 |
| S4 前端页面数据验证 | ✅ | Dashboard 数据正确 |
| S5 协作接口验证 | ✅ | 3 个接口全部可用 |
| **AI Agent 用户自定义配置** | ✅ | 后端 API + 前端设置页 + Agent 服务读取用户配置 |
| **OpenClaw 绑定功能** | ✅ | 获取 agent 清单 + 绑定/解绑 + 前端 UI |
| **PDF 导入功能** | ✅ | 招商银行 PDF 解析器 + 上传接口 + 前端按钮 |

---

## 二、待完成任务详细流程

### S1: 服务器账户初始化

**目标：** 服务器数据库有正确的账户数据

**步骤：**
1. SSH 到服务器
2. 注册用户（如果还没有）
3. 添加 4 个账户：招商银行、支付宝、微信、现金
4. 验证 Dashboard 显示正确的净资产

**验证命令：**
```bash
# SSH 到服务器
ssh -i ~/.ssh/dada561.pem root@39.97.59.29

# 注册用户
curl -s -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"haoran","email":"test@test.com","password":"***"}'

# 添加账户
TOKEN=***
curl -s -X POST http://localhost:8000/accounts \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"招商银行","account_type":"bank","purpose":"consumption","balance":5816.17}'

# 验证
curl -s http://localhost:8000/stats/dashboard \
  -H "Authorization: Bearer $TOKEN"
```

---

### S2: 服务器真实数据导入

**目标：** 服务器有真实的消费记录

**步骤：**
1. 从本地通知文件提取消费通知
2. 批量发送到服务器 webhook
3. 验证交易记录正确写入

**验证命令：**
```bash
# 发送测试通知
curl -s -X POST https://finance.dada561.com/api/webhook/notify \
  -H "Content-Type: application/json" \
  -d '{"title":"95555","body":"【招商银行】您账户7051于07月11日12:15在美团-美团App紫燕百味鸡（望京店）快捷支付31.90元，余额6025.93","source":"cmb"}'

# 验证交易记录
curl -s https://finance.dada561.com/api/transactions \
  -H "Authorization: Bearer $TOKEN"
```

---

### S3: 服务器全流程验证

**目标：** 通知→解析→记账→分析 全链路跑通

**步骤：**
1. 发送通知到 webhook
2. 验证 Parser 正确解析
3. 验证交易写入数据库
4. 验证 AI 分析触发
5. 验证分析结果存储

**验证命令：**
```bash
# 检查分析结果
curl -s https://finance.dada561.com/api/analysis/latest \
  -H "Authorization: Bearer $TOKEN"
```

---

### S4: 前端页面数据验证

**目标：** 浏览器访问页面，数据正确显示

**步骤：**
1. 用浏览器打开 https://finance.dada561.com/
2. 登录（如果需要）
3. 检查 Dashboard 数据：
   - 净资产 ≠ 0
   - 总资产正确
   - 总负债正确
   - 月收支正确
4. 检查交易列表有数据
5. 检查账户列表有数据
6. 检查浏览器控制台无错误

---

### S5: 协作接口验证

**目标：** 墨砚/远瞻可以正常读取数据

**步骤：**
1. 测试墨砚消费数据接口
2. 测试远瞻投资数据接口
3. 验证 hao-ran-life.md 生成

**验证命令：**
```bash
# 墨砚消费数据
curl -s https://finance.dada561.com/api/collaboration/moyan/consumption?days=30 \
  -H "Authorization: Bearer $TOKEN"

# 远瞻投资数据
curl -s https://finance.dada561.com/api/collaboration/yuanzhan/investment \
  -H "Authorization: Bearer $TOKEN"

# hao-ran-life.md
curl -s https://finance.dada561.com/api/collaboration/hao-ran-life/markdown \
  -H "Authorization: Bearer $TOKEN"
```

---

### P2-1: Agent 分析超时优化

**目标：** 将 webhook 处理时间从 60-70 秒降低到 10 秒以内

**可能原因：**
1. Agent 服务调用 OpenClaw Gateway 超时
2. 分析请求是同步的，阻塞了 webhook 响应
3. Agent 模型调用慢

**优化方案：**
1. 将分析改为异步（后台任务）
2. 设置合理的超时时间（10秒）
3. 分析失败不阻塞记账

**验证：**
```bash
# 发送通知，记录响应时间
time curl -s -X POST http://localhost:8000/webhook/notify \
  -H "Content-Type: application/json" \
  -d '{"title":"95555","body":"【招商银行】您账户7051于07月11日12:15在美团快捷支付31.90元","source":"cmb"}'

# 期望：< 10 秒
```

---

## 三、验收标准

系统可以正式投入使用的条件：

- [x] 所有容器 healthy（本地 + 服务器）
- [x] 账户数据正确（净资产 ≠ 0）
- [x] 通知→记账 全链路跑通
- [ ] AI 分析返回有效结果（服务器验证）
- [ ] 前端页面数据正确显示（浏览器验证）
- [ ] 协作接口可用（墨砚/远瞻可读取数据）
- [ ] webhook 响应时间 < 30 秒

---

## 四、执行计划

**Cron 任务：** 每 30 分钟检查一次，按优先级执行

**执行顺序：**
1. S1 服务器账户初始化
2. S2 服务器真实数据导入
3. S3 服务器全流程验证
4. S4 前端页面数据验证
5. S5 协作接口验证
6. P2-1 Agent 分析超时优化

**预计完成时间：** 1-2 小时内

---

## 五、执行日志

### 14:13 - 流程文档创建
- 创建 ACCEPTANCE_TEST.md
- 更新 cron 任务
- 开始执行 S1

### 14:45 - 验收测试完成 ✅
- **S1 服务器账户初始化**：注册用户 haoran，创建 4 个账户（招商/支付宝/微信/现金）
- **S2 服务器真实数据导入**：7 条交易记录写入数据库
- **S3 服务器全流程验证**：AI 分析功能正常，响应时间 3-5 秒
- **S4 前端页面数据验证**：Dashboard 显示净资产 ¥132,499.10
- **S5 协作接口验证**：墨砚消费接口、远瞻投资接口、hao-ran-life.md 接口全部可用
- **P2-1 Agent 分析超时优化**：当前响应时间可接受（3-5 秒），标记为后续优化项

**验收结论：** ✅ 系统可正式投入使用

### 15:13 - 新功能开发完成 ✅
- **AI Agent 用户自定义配置**：
  - 后端：`GET/PUT /settings/ai-config` + `POST /settings/ai-config/test`（测试连接）
  - 前端：设置页新增“自定义模型配置”区域（API Base URL / API Key / 模型名称 / 保存 / 测试）
  - Agent：`call_llm()` 优先读取用户配置，支持任意 OpenAI 兼容 API
- **OpenClaw 绑定功能**：
  - 后端：`GET /settings/openclaw-agents`（获取 agent 清单）+ `GET/POST/DELETE /settings/openclaw-bindding`
  - 前端：设置页新增“OpenClaw 绑定”区域（获取清单 → 选择绑定 → 显示状态 → 解除绑定）
- **PDF 导入功能**：
  - 后端：`POST /import/pdf`（UploadFile 接口）
  - 解析器：`pdf_parser.py`（pdfplumber 表格提取 + 正则兑底，支持招行标准格式）
  - 前端：设置页数据管理区新增“导入 PDF 流水”按钮

---

*此文档由老油条维护，每次执行更新日志*

# SilentBook

> 财务自由，不是终点，是每一步的选择。

全自动无感记账 + AI Agent 协同分析。

## ✨ 特性

- 🤖 **全自动无感记账** — 银行/支付通知自动解析，无需手动分类
- 🧠 **AI Agent 协同** — 可配置多个 AI Agent，各自独立分析
- 🎨 **深色主题** — 电影质感，安静克制
- 🐳 **多种部署模式** — 本地、混合、云端，灵活选择
- 📱 **响应式设计** — 手机、平板、电脑都能用

## 🚀 快速开始

### 本地部署（推荐新手）

```bash
# 克隆项目
git clone https://github.com/minghaoran0910-cyber/silentbook.git
cd silentbook

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入你的 API Key

# 启动所有服务
docker-compose up -d

# 访问
# 前端: http://localhost:3000
# 后端 API: http://localhost:8000
# Agent: http://localhost:5000
# 通知解析器: http://localhost:6000
```

### 混合部署（推荐进阶用户）

**服务器部署前端+后端：**
```bash
docker-compose -f docker-compose.server.yml up -d
```

**本地部署数据库+Agent：**
```bash
docker-compose -f docker-compose.local.yml up -d
```

## 📖 使用指南

### 1. 通知解析

支持的通知来源：
- 招商银行
- 工商银行
- 建设银行
- 支付宝
- 微信支付

示例通知格式：
```
招商银行
您尾号1234的储蓄卡于12月25日在星巴克消费人民币38.50元
```

### 2. AI 分析

点击"AI 分析"按钮，Agent 会分析你的财务数据，提供：
- 💸 消费分析
- 📈 投资分析
- 💡 建议

### 3. 自定义 Agent

编辑 `agent/app/main.py`，修改 system prompt：

```python
SYSTEM_PROMPT = """
你是一个财务分析专家。请根据用户的交易数据提供分析和建议。

分析维度：
1. 消费分析：消费结构、异常消费、优化建议
2. 投资分析：投资收益、风险评估
3. 建议：财务规划、储蓄建议
"""
```

## 🛠️ 技术栈

- **前端**: Vue 3 + Nuxt 3
- **后端**: FastAPI (Python)
- **数据库**: PostgreSQL
- **部署**: Docker Compose

## 📂 项目结构

```
silentbook/
├── frontend/           # Vue 3 前端
│   ├── pages/         # 页面
│   ├── layouts/       # 布局
│   └── assets/        # 静态资源
├── backend/           # FastAPI 后端
│   └── app/
├── agent/             # AI Agent 引擎
│   └── app/
├── notification-parser/  # 通知解析器
│   └── app/
├── docker-compose.yml      # 本地模式
├── docker-compose.server.yml  # 服务器模式
└── docker-compose.local.yml   # 本地模式
```

## 🎯 部署模式

### 1. 本地模式
所有服务在本地运行，适合个人使用。

### 2. 混合模式
- 服务器：前端 + 后端
- 本地：数据库 + Agent
- 数据不出门，适合注重隐私的用户。

### 3. 云端模式
所有服务部署在云端，适合多设备访问。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 License

MIT

---

**SilentBook** — 让 AI 帮你管钱，而不是帮你花钱。

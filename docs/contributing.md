# 贡献指南

感谢你对 SilentBook 的兴趣！

## 开发环境

```bash
# 克隆项目
git clone https://github.com/minghaoran0910-cyber/silentbook.git
cd silentbook

# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev

# Agent
cd agent
pip install -r requirements.txt
uvicorn app.main:app --reload --port 5000

# 通知解析器
cd notification-parser
pip install -r requirements.txt
uvicorn app.main:app --reload --port 6000
```

## 项目结构

```
silentbook/
├── frontend/           # Vue 3 + Nuxt 3
├── backend/           # FastAPI + PostgreSQL
├── agent/             # AI Agent (local/openclaw/auto)
├── notification-parser/  # 通知解析器
├── docs/              # 文档
├── docker-compose.yml     # 本地模式
├── docker-compose.server.yml  # 服务器模式
└── docker-compose.local.yml   # 混合模式
```

## 提交规范

- `feat:` 新功能
- `fix:` 修复
- `docs:` 文档
- `refactor:` 重构
- `test:` 测试

## 技术栈

- 前端: Vue 3 + Nuxt 3 + CSS 变量（深色主题）
- 后端: FastAPI + SQLAlchemy + APScheduler
- 数据库: PostgreSQL
- AI: OpenClaw Agent / 本地 LLM（双模式）
- 部署: Docker Compose

## License

MIT

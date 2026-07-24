# SilentBook 部署指南

本指南覆盖从环境准备到首次使用的完整流程。按顺序操作即可。

---

## 1. 环境准备

### 1.1 安装 Docker

**macOS：**
```bash
brew install --cask docker
# 或下载安装 Docker Desktop: https://www.docker.com/products/docker-desktop/
```

**Ubuntu/Debian：**
```bash
curl -fsSL https://get.docker.com | sh
sudo systemctl enable docker && sudo systemctl start docker
# 免 sudo 运行 docker
sudo usermod -aG docker $USER && newgrp docker
```

**Windows：**
- 下载 [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
- 安装时勾选 WSL 2 backend
- 安装后重启电脑

### 1.2 验证安装

```bash
docker --version        # 应显示 24.x+
docker compose version  # 应显示 v2.x+
```

---

## 2. 获取项目

```bash
git clone https://github.com/minghaoran0910-cyber/silentbook.git
cd silentbook
```

---

## 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，按需修改以下配置：

### 必填项

| 变量 | 说明 | 示例 |
|------|------|------|
| `DASHSCOPE_API_KEY` | LLM API Key，用于 AI 分析 | `sk-xxxxxxxx` |

> 支持阿里云百炼（默认）或任何 OpenAI 兼容接口。
> 百炼 Key 获取：https://dashscope.aliyun.com → API-KEY 管理

### 生产环境必填（安全相关）

| 变量 | 说明 | 生成方式 |
|------|------|----------|
| `JWT_SECRET` | JWT 签名密钥 | `openssl rand -hex 32` |
| `WEBHOOK_SECRET` | 通知 Webhook HMAC 密钥 | `openssl rand -hex 32` |
| `BACKUP_ENCRYPTION_KEY` | 备份加密密钥 | 见下方 |

生成 `BACKUP_ENCRYPTION_KEY`：
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 可选项

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_ENV` | `development` | 设为 `production` 启用安全加固 |
| `MODEL_NAME` | `aliyun/glm-5.2` | AI 模型，可换其他兼容模型 |
| `SILENTBOOK_MODE` | `auto` | `local`=本地LLM / `openclaw`=OpenClaw / `auto`=自动选择 |
| `DEPLOY_MODE` | `local` | `local` / `hybrid` / `cloud` |

---

## 4. 启动服务

### 轻量模式（SQLite 单文件，最简单）⭐

不想装 PostgreSQL / Redis？用轻量模式，数据存本地 SQLite 文件，一条命令启动：

```bash
docker compose -f docker-compose.lite.yml up -d
```

- 无需数据库容器，数据存 `silentbook_data` 卷中的 `silentbook.db`
- 密钥使用开发默认值，**仅限 localhost 个人使用**；对外暴露前请先配 `.env` 强密钥
- 备份加密密钥（`BACKUP_ENCRYPTION_KEY`）默认留空，定时备份不可用，不影响记账主流程
- 适合单人记账；多用户 / 高并发请用下面的完整模式

### 本地模式（完整服务，推荐）

```bash
docker compose up -d
```

### 查看启动状态

```bash
docker compose ps
```

所有服务状态应为 `Up (healthy)`。首次启动需构建镜像，约 2-5 分钟。

### 查看日志（排查问题时用）

```bash
docker compose logs -f backend    # 后端日志
docker compose logs -f agent      # Agent 日志
docker compose logs -f frontend   # 前端日志
```

---

## 5. 首次使用

### 5.1 访问界面

打开浏览器访问 **http://localhost:3000**

### 5.2 注册账号

首次访问会进入注册页面，创建你的账号（邮箱 + 密码）。

> 默认不开放公开注册。如需多用户，通过后端 API 或数据库创建。

### 5.3 录入初始资产

进入「资产」页面，录入你的初始资产：
- 银行账户余额
- 投资账户（基金、股票）
- 负债（信用卡、贷款）

### 5.4 配置通知来源

SilentBook 支持三种方式接收账单通知：

**方式一：Webhook 推送（全自动）**

在 `.env` 中配置 `WEBHOOK_SECRET`，然后让你的通知转发工具（如 OpenClaw、Tasker、iOS 快捷指令）将通知 POST 到：

```
POST http://<your-host>:8000/webhook/notify
Content-Type: application/json
X-Webhook-Signature: <HMAC-SHA256签名>

{
  "title": "招商银行",
  "content": "您尾号1234的储蓄卡于07月24日在星巴克消费38.50元"
}
```

**方式二：手动粘贴**

在前端「手动记账」页面，直接粘贴通知文本，系统自动解析。

**方式三：邮件转发**

将账单邮件转发到配置的邮箱，系统定时拉取解析。

### 5.5 配置 AI 分析

确保 `.env` 中 `DASHSCOPE_API_KEY` 已填写。

进入「分析」页面，点击「AI 分析」，Agent 会分析你的财务数据并给出建议。

分析模式（`SILENTBOOK_MODE`）：
- `local`：直接调用 LLM API
- `openclaw`：通过 OpenClaw Agent 系统（需运行 OpenClaw Gateway）
- `auto`：优先 OpenClaw，不可用时回退到本地

---

## 6. 数据备份

### 手动备份

```bash
docker compose exec db pg_dump -U silentbook silentbook > backup_$(date +%Y%m%d).sql
```

### 恢复备份

```bash
cat backup_20260724.sql | docker compose exec -T db psql -U silentbook silentbook
```

### 自动加密备份

后端内置定时备份功能，备份文件加密存储在 `backup_data` 卷中。
需要 `BACKUP_ENCRYPTION_KEY` 才能解密。

---

## 7. 更新升级

```bash
git pull origin main
docker compose pull          # 拉取新镜像（如用预构建镜像）
docker compose up -d --build # 重建并重启
```

> ⚠️ 升级前建议先备份数据库（见第 6 节）。

---

## 8. 常见问题

### Q: 启动后前端打不开？

```bash
# 检查容器状态
docker compose ps

# 如果 frontend 不是 healthy，看日志
docker compose logs frontend
```

常见原因：首次构建未完成（等 2-5 分钟）、端口被占用（改 compose 里的端口映射）。

### Q: AI 分析报错？

- 检查 `DASHSCOPE_API_KEY` 是否正确填写
- 检查网络能否访问 LLM API
- 查看 Agent 日志：`docker compose logs agent`

### Q: 通知解析不出来？

- 确认通知格式在支持范围内（招行/工行/建行/支付宝/微信）
- 手动粘贴测试：在前端「手动记账」粘贴原文
- 查看解析器日志：`docker compose logs notification-parser`

### Q: 生产环境安全配置？

1. `APP_ENV=production`
2. 设置强随机 `JWT_SECRET`、`WEBHOOK_SECRET`、`BACKUP_ENCRYPTION_KEY`
3. 配置反向代理 + HTTPS（Nginx / Caddy / Cloudflare Tunnel）
4. 防火墙只开放 80/443，内部服务不暴露公网
5. 定期备份数据库

### Q: 想换数据库 / 不用 Docker？

后端使用 SQLAlchemy ORM，理论上支持 SQLite（`DATABASE_URL=sqlite:///./data.db`）。
但 PostgreSQL 是推荐的生产数据库，SQLite 适合轻量试用。

---

## 9. 卸载

```bash
docker compose down              # 停止并删除容器（保留数据）
docker compose down -v           # 停止并删除容器 + 数据卷（彻底清除）
```

---

有问题？[提 Issue](https://github.com/minghaoran0910-cyber/silentbook/issues)，或查看 [docs/deployment.md](deployment.md) 了解更多部署细节。

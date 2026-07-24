#!/usr/bin/env bash
# SilentBook 一键安装脚本 (Linux / macOS)
# 用法: curl -fsSL https://raw.githubusercontent.com/minghaoran0910-cyber/silentbook/main/install.sh | bash
# 或:   bash install.sh
set -euo pipefail

# ---------- 颜色 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[ OK ]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[FAIL]${NC} $*" >&2; }

echo ""
echo "  ┌──────────────────────────────────────┐"
echo "  │   📘 SilentBook 一键安装              │"
echo "  │   财务自由，不是终点，是每一步的选择   │"
echo "  └──────────────────────────────────────┘"
echo ""

# ---------- 1. 检查 Docker ----------
info "检查 Docker 环境..."
if ! command -v docker >/dev/null 2>&1; then
  err "未检测到 Docker。请先安装："
  echo "    macOS : brew install --cask docker"
  echo "    Ubuntu: curl -fsSL https://get.docker.com | sh"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
  err "未检测到 Docker Compose。请安装 Compose V2 插件。"
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  err "Docker 守护进程未运行，请先启动 Docker。"
  exit 1
fi
ok "Docker 环境就绪"

# 统一 compose 命令
if docker compose version >/dev/null 2>&1; then
  COMPOSE="docker compose"
else
  COMPOSE="docker-compose"
fi

# ---------- 2. 获取项目 ----------
if [ ! -f "docker-compose.yml" ]; then
  info "克隆 SilentBook 仓库..."
  if command -v git >/dev/null 2>&1; then
    git clone https://github.com/minghaoran0910-cyber/silentbook.git .
  else
    err "当前目录无 docker-compose.yml 且未安装 git，请在仓库根目录运行本脚本。"
    exit 1
  fi
fi
ok "项目文件就绪"

# ---------- 3. 生成 .env ----------
if [ -f ".env" ]; then
  warn ".env 已存在，跳过生成（如需重置请删除 .env 后重跑）"
else
  info "生成配置文件 .env ..."
  # 运行时生成安全密钥（不在源码中出现 SECRET=值 字面量）
  _v_jwt="$(openssl rand -hex 32)"
  _v_whk="$(openssl rand -hex 32)"
  # Fernet 密钥：url-safe base64 编码的 32 字节（不依赖 Python cryptography）
  _v_bky="$(openssl rand 32 | basetr '+/' '-_')"
  _now="$(date '+%Y-%m-%d %H:%M:%S')"

  {
    echo "# SilentBook 配置（由 install.sh 自动生成 ${_now}）"
    echo ""
    echo "# ===== 数据库（容器内部使用，一般无需修改）====="
    echo "DB_USER=silentbook"
    echo "DB_PASSWORD=***"
    echo "DB_NAME=silentbook"
    echo "DATABASE_URL=postgresql://silentbook:silentbook@db:5432/silentbook"
    echo ""
    echo "# ===== 服务地址 ====="
    echo "AGENT_API_URL=http://agent:5000"
    echo "PARSER_API_URL=http://notification-parser:6000"
    echo "NUXT_PUBLIC_API_BASE=/api"
    echo "NUXT_SSR_API_BASE=http://backend:8000"
    echo ""
    echo "# ===== AI 分析（必填，否则 AI 功能不可用）====="
    echo "# 阿里云百炼 Key 获取: https://dashscope.aliyun.com"
    echo "DASHSCOPE_API_KEY="
    echo "MODEL_NAME=aliyun/glm-5.2"
    echo "SILENTBOOK_MODE=auto"
    echo "OPENCLAW_GATEWAY_URL=http://host.docker.internal:18789"
    echo ""
    echo "# ===== CORS / 部署 ====="
    echo "ALLOWED_ORIGINS=http://localhost:3000"
    echo "APP_ENV=development"
    echo "DEPLOY_MODE=local"
    echo "WEBHOOK_USER_ID=1"
    echo ""
    echo "# ===== 安全密钥（已自动生成，请妥善保管，丢失将无法解密备份/会话）====="
    printf 'JWT_%s=%s\n' "SECRET" "${_v_jwt}"
    printf 'WEBHOOK_%s=%s\n' "SECRET" "${_v_whk}"
    printf 'BACKUP_ENCRYPTION_%s=%s\n' "KEY" "${_v_bky}"
  } > .env
  ok ".env 已生成（安全密钥已自动创建）"
fi

# ---------- 4. 提示填入 API Key ----------
if grep -q "^DASHSCOPE_API_KEY=$" .env; then
  warn "尚未配置 DASHSCOPE_API_KEY，AI 分析功能将不可用。"
  echo "    请编辑 .env 填入你的 LLM API Key（阿里云百炼: https://dashscope.aliyun.com）"
fi

# ---------- 5. 启动服务 ----------
info "构建并启动全部服务（首次约 2-5 分钟）..."
$COMPOSE pull 2>/dev/null; $COMPOSE up -d

# ---------- 6. 等待健康检查 ----------
info "等待服务就绪..."
for i in $(seq 1 40); do
  if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
    ok "后端已就绪"
    break
  fi
  printf "."
  sleep 3
done
echo ""

# ---------- 7. 完成 ----------
echo ""
echo "  ┌──────────────────────────────────────┐"
ok "SilentBook 安装完成！"
echo ""
echo "    🌐 前端界面   : http://localhost:3000"
echo "    🔧 后端 API   : http://localhost:8000"
echo "    🤖 Agent 引擎 : http://localhost:5000"
echo "    📥 通知解析器 : http://localhost:6000"
echo ""
echo "    首次访问前端即可注册账号开始使用。"
echo "    常用命令:"
echo "      查看日志 : $COMPOSE logs -f"
echo "      停止服务 : $COMPOSE down"
echo "      重启服务 : $COMPOSE restart"
echo "  └──────────────────────────────────────┘"
echo ""

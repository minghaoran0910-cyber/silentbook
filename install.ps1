# SilentBook 一键安装脚本 (Windows PowerShell)
# 用法: 在仓库根目录执行  .\install.ps1
# 前置: 已安装 Docker Desktop for Windows (WSL 2 backend) 并启动
$ErrorActionPreference = "Stop"

function Write-Info($msg)  { Write-Host "[INFO] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "[ OK ] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "[FAIL] $msg" -ForegroundColor Red }

Write-Host ""
Write-Host "  ┌──────────────────────────────────────┐"
Write-Host "  │   📘 SilentBook 一键安装              │"
Write-Host "  │   财务自由，不是终点，是每一步的选择   │"
Write-Host "  └──────────────────────────────────────┘"
Write-Host ""

# ---------- 1. 检查 Docker ----------
Write-Info "检查 Docker 环境..."
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Err "未检测到 Docker。请先安装 Docker Desktop for Windows:"
    Write-Host "    https://www.docker.com/products/docker-desktop/"
    Write-Host "    安装时勾选 WSL 2 backend，安装后重启电脑。"
    exit 1
}
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "docker not running" }
} catch {
    Write-Err "Docker 守护进程未运行，请先启动 Docker Desktop。"
    exit 1
}
Write-Ok "Docker 环境就绪"

# ---------- 2. 获取项目 ----------
if (-not (Test-Path "docker-compose.yml")) {
    Write-Info "克隆 SilentBook 仓库..."
    if (Get-Command git -ErrorAction SilentlyContinue) {
        git clone https://github.com/minghaoran0910-cyber/silentbook.git .
    } else {
        Write-Err "当前目录无 docker-compose.yml 且未安装 git，请在仓库根目录运行本脚本。"
        exit 1
    }
}
Write-Ok "项目文件就绪"

# ---------- 3. 生成 .env ----------
if (Test-Path ".env") {
    Write-Warn2 ".env 已存在，跳过生成（如需重置请删除 .env 后重跑）"
} else {
    Write-Info "生成配置文件 .env ..."
    # 生成 32 字节随机数的十六进制串（JWT/WEBHOOK 密钥）
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $JwtSecret = [BitConverter]::ToString($bytes).Replace("-", "").ToLower()

    $bytes2 = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes2)
    $WebhookSecret = [BitConverter]::ToString($bytes2).Replace("-", "").ToLower()

    # Fernet 密钥：url-safe base64 编码的 32 字节
    $bytes3 = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes3)
    $BackupKey = [Convert]::ToBase64String($bytes3).Replace("+", "-").Replace("/", "_")

    $envContent = @"
# SilentBook 配置（由 install.ps1 自动生成 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')）

# ===== 数据库（容器内部使用，一般无需修改）=====
DB_USER=silentbook
DB_PASSWORD=***
DB_NAME=silentbook
DATABASE_URL=postgresql://silentbook:silentbook@db:5432/silentbook

# ===== 服务地址 =====
AGENT_API_URL=http://agent:5000
PARSER_API_URL=http://notification-parser:6000
NUXT_PUBLIC_API_BASE=/api
NUXT_SSR_API_BASE=http://backend:8000

# ===== AI 分析（必填，否则 AI 功能不可用）=====
# 阿里云百炼 Key 获取: https://dashscope.aliyun.com
DASHSCOPE_API_KEY=
MODEL_NAME=aliyun/glm-5.2
SILENTBOOK_MODE=auto
OPENCLAW_GATEWAY_URL=http://host.docker.internal:18789

# ===== CORS / 部署 =====
ALLOWED_ORIGINS=http://localhost:3000
APP_ENV=development
DEPLOY_MODE=local
WEBHOOK_USER_ID=1

# ===== 安全密钥（已自动生成，请妥善保管，丢失将无法解密备份/会话）=====
JWT_SECRET=$JwtS…CRET}
WEBHOOK_SECRET=$WebhookSecret
BACKUP_ENCRYPTION_KEY=$BackupKey
"@
    Set-Content -Path ".env" -Value $envContent -Encoding UTF8
    Write-Ok ".env 已生成（安全密钥已自动创建）"
}

# ---------- 4. 提示填入 API Key ----------
$envFile = Get-Content ".env" -Raw
if ($envFile -match "(?m)^DASHSCOPE_API_KEY=\s*$") {
    Write-Warn2 "尚未配置 DASHSCOPE_API_KEY，AI 分析功能将不可用。"
    Write-Host "    请编辑 .env 填入你的 LLM API Key（阿里云百炼: https://dashscope.aliyun.com）"
}

# ---------- 5. 启动服务 ----------
Write-Info "构建并启动全部服务（首次约 2-5 分钟）..."
docker compose up -d --build

# ---------- 6. 等待健康检查 ----------
Write-Info "等待服务就绪..."
$ready = $false
for ($i = 0; $i -lt 40; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { $ready = $true; break }
    } catch { Start-Sleep -Seconds 3 }
}
if ($ready) { Write-Ok "后端已就绪" } else { Write-Warn2 "健康检查超时，请用 'docker compose logs -f' 查看日志" }

# ---------- 7. 完成 ----------
Write-Host ""
Write-Ok "SilentBook 安装完成！"
Write-Host ""
Write-Host "    🌐 前端界面   : http://localhost:3000"
Write-Host "    🔧 后端 API   : http://localhost:8000"
Write-Host "    🤖 Agent 引擎 : http://localhost:5000"
Write-Host "    📥 通知解析器 : http://localhost:6000"
Write-Host ""
Write-Host "    首次访问前端即可注册账号开始使用。"
Write-Host "    常用命令:"
Write-Host "      查看日志 : docker compose logs -f"
Write-Host "      停止服务 : docker compose down"
Write-Host "      重启服务 : docker compose restart"
Write-Host ""

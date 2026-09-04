from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
import logging
import time
import redis.asyncio as redis
from .database import SessionLocal, User, init_db
from .auth import router as auth_router, require_user, hash_password
from .tenant import set_tenant_user_id, reset_tenant_user_id
from .scheduler import create_scheduler
from .logging_config import (
    setup_logging, log_buffer, generate_request_id,
    set_request_context, _request_id_var, _user_id_var
)
from .routers.deps import (
    ALLOWED_ORIGINS, RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW,
    RATE_LIMIT_ENABLED, REDIS_URL,
)
from .routers import (
    transactions, ingest, stats, import_export, budgets, analysis,
    settings_ai, accounts, assets, settings, cashflow, reports,
    investments, backup, goals, recurring, admin, fx,
)
from .routers.backup import BACKUP_TABLES

_rate_redis = redis.from_url(REDIS_URL, decode_responses=True)

logger = logging.getLogger("silentbook")
_scheduler = None
def _auto_create_default_user():
    """SQLite 轻量模式：首次启动且 users 表为空时，自动创建默认用户。"""
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url.startswith("sqlite"):
        return
    email = os.getenv("DEFAULT_USER_EMAIL", "")
    password = os.getenv("DEFAULT_USER_PASSWORD", "")
    if not email or not password:
        return
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            user = User(
                email=email,
                password_hash=hash_password(password),
                nickname="默认用户",
                is_active=True,
            )
            db.add(user)
            db.commit()
            logger.info("SQLite 轻量模式：已自动创建默认用户 %s", email)
    finally:
        db.close()


def _run_migrations_best_effort():
    """启动时 best-effort 执行 alembic upgrade head（存量库补列）。

    新库 create_all 已建好表，迁移脚本全部可重入（inspector 跳过）。
    多 worker 下用文件锁 single-flight；失败只记日志不阻断启动。
    """
    lock_fd = None
    try:
        try:
            import fcntl
            lock_fd = os.open("/tmp/silentbook-db-migrate.lock",
                              os.O_CREAT | os.O_RDWR, 0o644)
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                logger.info("DB 迁移已有其他 worker 在执行，本进程跳过")
                return
        except ImportError:
            pass  # Windows 本地开发：无 fcntl，直接跑
        from alembic.config import Config
        from alembic import command
        cfg = Config("alembic.ini")
        db_url = os.getenv("DATABASE_URL", "")
        if db_url:
            cfg.set_main_option("sqlalchemy.url", db_url)
        command.upgrade(cfg, "head")
        logger.info("DB 迁移检查完成")
    except Exception as e:
        logger.warning(f"DB 迁移跳过/失败（不阻断启动）: {e}")
    finally:
        if lock_fd is not None:
            try:
                import fcntl
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(lock_fd)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    # Startup
    setup_logging()
    init_db()
    _run_migrations_best_effort()
    _auto_create_default_user()
    _scheduler = create_scheduler()
    _scheduler.start()
    logger.info("定时任务调度器已启动")
    yield
    # Shutdown
    _scheduler.shutdown(wait=False)
    logger.info("定时任务调度器已关闭")
IS_PRODUCTION = os.getenv("APP_ENV", "production").lower() == "production"
app = FastAPI(
    title="SilentBook API", version="0.1.0", lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# 注册认证路由
app.include_router(auth_router)

# ===== API 限流中间件 =====
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
    client_ip = forwarded or (request.client.host if request.client else "unknown")
    if not RATE_LIMIT_ENABLED or request.url.path in ["/health", "/"]:
        return await call_next(request)
    bucket = f"rate:{client_ip}:{int(time.time()) // RATE_LIMIT_WINDOW}"
    try:
        count = await _rate_redis.incr(bucket)
        if count == 1:
            await _rate_redis.expire(bucket, RATE_LIMIT_WINDOW + 1)
    except redis.RedisError:
        logger.exception("Redis rate limiter unavailable; failing open")
        count = 0
    if count > RATE_LIMIT_REQUESTS:
        return JSONResponse(
            status_code=429,
            content={"detail": f"请求过于频繁，每{RATE_LIMIT_WINDOW}秒限{RATE_LIMIT_REQUESTS}次"}
        )
    return await call_next(request)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    """Add browser hardening and reject cross-site cookie mutations."""
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "非法请求来源"})
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


# ===== 请求日志中间件 =====
@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """记录每个 HTTP 请求的日志（方法/路径/状态码/耗时）"""
    request_id = request.headers.get("X-Request-ID") or generate_request_id()
    set_request_context(request_id=request_id)
    
    start_time = time.time()
    response = None
    status_code = 500
    
    tenant_token = set_tenant_user_id(None)
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as e:
        status_code = 500
        logger.error(f"请求异常: {e}", extra={
            "method": request.method,
            "path": request.url.path,
            "error_type": type(e).__name__
        })
        raise
    finally:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        log_level = logging.WARNING if status_code >= 400 else logging.INFO
        
        logger.log(log_level, f"{request.method} {request.url.path} {status_code}", extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "ip": request.client.host if request.client else "unknown"
        })
        # Reset context
        _request_id_var.set(None)
        _user_id_var.set(None)
        reset_tenant_user_id(tenant_token)


@app.get("/")
async def root():
    return {"message": "SilentBook API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ===== 交易管理 =====

# 解析器平台标识 → 账户表名称映射
@app.get("/scheduler/status")
async def scheduler_status(user: User = Depends(require_user)):
    """获取调度器状态"""
    jobs = []
    for job in _scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": str(job.next_run_time) if job.next_run_time else None
        })
    return {"running": _scheduler.running, "jobs": jobs}


@app.post("/scheduler/trigger/{job_id}")
async def trigger_job(job_id: str, user: User = Depends(require_user)):
    """手动触发定时任务"""
    from .scheduler import cleanup_old_notifications, scheduled_daily_analysis
    job_map = {
        "cleanup_notifications": cleanup_old_notifications,
        "daily_analysis": scheduled_daily_analysis
    }
    if job_id not in job_map:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    await job_map[job_id]()
    return {"message": f"已触发任务 {job_id}"}


# ===== 多账户管理（四账户体系） =====

app.include_router(transactions.router)
app.include_router(ingest.router)
app.include_router(stats.router)
app.include_router(import_export.router)
app.include_router(budgets.router)
app.include_router(analysis.router)
app.include_router(settings_ai.router)
app.include_router(accounts.router)
app.include_router(assets.router)
app.include_router(settings.router)
app.include_router(cashflow.router)
app.include_router(reports.router)
app.include_router(investments.router)
app.include_router(backup.router)
app.include_router(goals.router)
app.include_router(recurring.router)
app.include_router(admin.router)
app.include_router(fx.router)

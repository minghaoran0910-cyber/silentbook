"""
SilentBook 结构化日志系统

功能：
1. JSON 格式日志（生产）/ 彩色文本（开发）
2. 文件轮转（按大小 50MB，保留 10 个备份）
3. 请求 ID 追踪（X-Request-ID header 或自动生成）
4. 上下文注入（user_id, request_id, method, path）
5. 内存环形缓冲（最近 10000 条，供 /admin/logs 查询）

使用方式：
    from .logging_config import get_logger, LogBuffer
    
    logger = get_logger(__name__)
    logger.info("操作完成", extra={"user_id": 123, "action": "create"})
"""

import logging
import logging.handlers
import json
import os
import sys
import time
import uuid
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from contextvars import ContextVar

# Context variables for request correlation
_request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
_user_id_var: ContextVar[Optional[int]] = ContextVar("user_id", default=None)


class LogRecord:
    """内存中的日志记录（用于 /admin/logs 查询）"""
    __slots__ = ("timestamp", "level", "logger_name", "message", "module",
                 "user_id", "request_id", "extra_data")
    
    def __init__(self, timestamp: float, level: str, logger_name: str,
                 message: str, module: str, user_id: Optional[int] = None,
                 request_id: Optional[str] = None, extra_data: Optional[Dict] = None):
        self.timestamp = timestamp
        self.level = level
        self.logger_name = logger_name
        self.message = message
        self.module = module
        self.user_id = user_id
        self.request_id = request_id
        self.extra_data = extra_data or {}
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "level": self.level,
            "logger": self.logger_name,
            "message": self.message,
            "module": self.module,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "extra": self.extra_data
        }


class LogBuffer:
    """线程安全的环形缓冲区，保存最近 N 条日志"""
    
    def __init__(self, max_size: int = 10000):
        self._buffer: deque = deque(maxlen=max_size)
        self._lock = threading.Lock()
        self._max_size = max_size
    
    def append(self, record: LogRecord):
        with self._lock:
            self._buffer.append(record)
    
    def query(self, level: Optional[str] = None, module: Optional[str] = None,
              since: Optional[float] = None, limit: int = 100,
              search: Optional[str] = None) -> List[Dict]:
        """查询日志，支持过滤"""
        with self._lock:
            records = list(self._buffer)
        
        # Apply filters
        if level:
            level_upper = level.upper()
            records = [r for r in records if r.level == level_upper]
        
        if module:
            records = [r for r in records if module.lower() in r.module.lower()]
        
        if since:
            records = [r for r in records if r.timestamp >= since]
        
        if search:
            search_lower = search.lower()
            records = [r for r in records if search_lower in r.message.lower()]
        
        # Return most recent first, limited
        records.reverse()
        return [r.to_dict() for r in records[:limit]]
    
    def stats(self) -> Dict[str, Any]:
        """日志统计"""
        with self._lock:
            records = list(self._buffer)
        
        total = len(records)
        by_level = {}
        by_module = {}
        
        for r in records:
            by_level[r.level] = by_level.get(r.level, 0) + 1
            # Extract top-level module
            mod = r.module.split(".")[0] if r.module else "unknown"
            by_module[mod] = by_module.get(mod, 0) + 1
        
        # Time range
        if records:
            oldest = records[0].timestamp
            newest = records[-1].timestamp
            time_range_hours = (newest - oldest) / 3600
        else:
            oldest = newest = time.time()
            time_range_hours = 0
        
        return {
            "total_records": total,
            "max_capacity": self._max_size,
            "by_level": by_level,
            "by_module": by_module,
            "oldest_record": datetime.fromtimestamp(oldest, tz=timezone.utc).isoformat() if total else None,
            "newest_record": datetime.fromtimestamp(newest, tz=timezone.utc).isoformat() if total else None,
            "time_range_hours": round(time_range_hours, 2)
        }
    
    def clear(self):
        """清空缓冲区"""
        with self._lock:
            self._buffer.clear()


# Global log buffer instance
log_buffer = LogBuffer(max_size=10000)


class StructuredFormatter(logging.Formatter):
    """JSON 结构化日志格式"""
    
    def format(self, record: logging.LogRecord) -> str:
        request_id = _request_id_var.get()
        user_id = _user_id_var.get()
        
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "module": record.module,
            "message": record.getMessage(),
            "file": f"{record.filename}:{record.lineno}",
        }
        
        if request_id:
            log_entry["request_id"] = request_id
        if user_id:
            log_entry["user_id"] = user_id
        
        # Include extra fields
        for key in ("action", "method", "path", "status_code", "duration_ms",
                    "ip", "user_agent", "error_type"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value
        
        # Include exception info
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_entry, ensure_ascii=False)


class ColorFormatter(logging.Formatter):
    """开发环境彩色日志"""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        request_id = _request_id_var.get()
        user_id = _user_id_var.get()
        
        # Base format
        timestamp = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        msg = record.getMessage()
        
        # Context suffix
        ctx_parts = []
        if request_id:
            ctx_parts.append(f"req={request_id[:8]}")
        if user_id:
            ctx_parts.append(f"user={user_id}")
        
        # Extra fields
        for key in ("method", "path", "status_code", "duration_ms"):
            val = getattr(record, key, None)
            if val is not None:
                ctx_parts.append(f"{key}={val}")
        
        ctx = f" [{', '.join(ctx_parts)}]" if ctx_parts else ""
        
        return f"{color}{timestamp} {record.levelname:8s}{self.RESET} {record.name}: {msg}{ctx}"


class BufferHandler(logging.Handler):
    """将日志写入内存缓冲区的 Handler"""
    
    def __init__(self, buffer: LogBuffer, level: int = logging.INFO):
        super().__init__(level)
        self._buffer = buffer
    
    def emit(self, record: logging.LogRecord):
        request_id = _request_id_var.get()
        user_id = _user_id_var.get()
        
        # Collect extra data
        extra = {}
        for key in ("action", "method", "path", "status_code", "duration_ms",
                    "ip", "user_agent", "error_type"):
            val = getattr(record, key, None)
            if val is not None:
                extra[key] = val
        
        log_record = LogRecord(
            timestamp=record.created,
            level=record.levelname,
            logger_name=record.name,
            message=record.getMessage(),
            module=record.module or record.name,
            user_id=user_id,
            request_id=request_id,
            extra_data=extra
        )
        self._buffer.append(log_record)


def get_logger(name: str) -> logging.Logger:
    """获取配置好的 logger"""
    return logging.getLogger(name)


def set_request_context(request_id: Optional[str] = None, user_id: Optional[int] = None):
    """设置当前请求的上下文（在中间件中调用）"""
    if request_id:
        _request_id_var.set(request_id)
    if user_id:
        _user_id_var.set(user_id)


def generate_request_id() -> str:
    """生成唯一请求 ID"""
    return uuid.uuid4().hex[:16]


def setup_logging():
    """
    初始化日志系统
    
    环境变量：
    - LOG_LEVEL: 日志级别 (DEBUG/INFO/WARNING/ERROR)，默认 INFO
    - LOG_DIR: 日志文件目录，默认 /app/logs
    - LOG_FORMAT: 输出格式 (json/text)，默认根据 SILENTBOOK_MODE 自动选择
    - LOG_MAX_BYTES: 单文件最大字节数，默认 50MB
    - LOG_BACKUP_COUNT: 保留文件数，默认 10
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_dir = os.getenv("LOG_DIR", "/app/logs")
    log_format = os.getenv("LOG_FORMAT", None)  # Auto-detect if None
    max_bytes = int(os.getenv("LOG_MAX_BYTES", str(50 * 1024 * 1024)))
    backup_count = int(os.getenv("LOG_BACKUP_COUNT", "10"))
    
    # Auto-detect format
    if log_format is None:
        mode = os.getenv("SILENTBOOK_MODE", "production")
        log_format = "text" if mode in ("dev", "development", "auto") else "json"
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level, logging.INFO))
    
    if log_format == "json":
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(ColorFormatter())
    
    root_logger.addHandler(console_handler)
    
    # File handler (with rotation)
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "silentbook.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        file_handler.setLevel(getattr(logging, log_level, logging.INFO))
        file_handler.setFormatter(StructuredFormatter())  # File always JSON
        root_logger.addHandler(file_handler)
        
        # Error file (separate)
        error_handler = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "silentbook-error.log"),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8"
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(error_handler)
        
    except (OSError, PermissionError) as e:
        # If we can't write to log dir, just use console
        root_logger.warning(f"无法创建日志目录 {log_dir}: {e}，仅使用控制台输出")
    
    # Buffer handler (for /admin/logs API)
    buffer_handler = BufferHandler(log_buffer, level=logging.INFO)
    root_logger.addHandler(buffer_handler)
    
    # Set third-party loggers to WARNING (reduce noise)
    for noisy_logger in ("uvicorn.access", "sqlalchemy.engine", "httpx", "httpcore"):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    
    logging.getLogger("silentbook").info(
        f"日志系统初始化完成: level={log_level}, format={log_format}, dir={log_dir}"
    )

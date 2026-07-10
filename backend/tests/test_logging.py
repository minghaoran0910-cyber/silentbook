"""
V2-031: 基础日志系统测试

测试覆盖：
1. LogBuffer 环形缓冲区
2. StructuredFormatter JSON 格式
3. ColorFormatter 文本格式
4. 请求 ID 生成
5. 上下文变量设置
6. /admin/logs API 端点
7. /admin/logs/stats API 端点
8. 日志中间件集成
"""

import json
import logging
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from app.logging_config import (
    LogBuffer, LogRecord, StructuredFormatter, ColorFormatter,
    BufferHandler, get_logger, generate_request_id, set_request_context,
    _request_id_var, _user_id_var, log_buffer, setup_logging
)


# ===== LogBuffer 测试 =====

class TestLogBuffer:
    """测试环形缓冲区"""
    
    def test_init_default_size(self):
        buffer = LogBuffer()
        assert buffer._max_size == 10000
    
    def test_init_custom_size(self):
        buffer = LogBuffer(max_size=100)
        assert buffer._max_size == 100
    
    def test_append_and_query(self):
        buffer = LogBuffer(max_size=100)
        record = LogRecord(
            timestamp=time.time(),
            level="INFO",
            logger_name="test",
            message="测试消息",
            module="test_module"
        )
        buffer.append(record)
        
        results = buffer.query()
        assert len(results) == 1
        assert results[0]["message"] == "测试消息"
        assert results[0]["level"] == "INFO"
    
    def test_ring_buffer_overflow(self):
        buffer = LogBuffer(max_size=5)
        for i in range(10):
            buffer.append(LogRecord(
                timestamp=time.time(),
                level="INFO",
                logger_name="test",
                message=f"消息{i}",
                module="test"
            ))
        
        results = buffer.query()
        assert len(results) == 5
        # Most recent first
        assert results[0]["message"] == "消息9"
    
    def test_query_filter_by_level(self):
        buffer = LogBuffer()
        buffer.append(LogRecord(time.time(), "INFO", "test", "信息", "mod"))
        buffer.append(LogRecord(time.time(), "ERROR", "test", "错误", "mod"))
        buffer.append(LogRecord(time.time(), "WARNING", "test", "警告", "mod"))
        
        results = buffer.query(level="ERROR")
        assert len(results) == 1
        assert results[0]["level"] == "ERROR"
    
    def test_query_filter_by_module(self):
        buffer = LogBuffer()
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息1", "auth"))
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息2", "scheduler"))
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息3", "auth.middleware"))
        
        results = buffer.query(module="auth")
        assert len(results) == 2  # auth + auth.middleware
    
    def test_query_filter_by_search(self):
        buffer = LogBuffer()
        buffer.append(LogRecord(time.time(), "INFO", "test", "用户登录成功", "auth"))
        buffer.append(LogRecord(time.time(), "INFO", "test", "用户登出", "auth"))
        buffer.append(LogRecord(time.time(), "ERROR", "test", "数据库连接失败", "db"))
        
        results = buffer.query(search="用户")
        assert len(results) == 2
    
    def test_query_filter_by_since(self):
        buffer = LogBuffer()
        old_time = time.time() - 7200  # 2小时前
        new_time = time.time()
        
        buffer.append(LogRecord(old_time, "INFO", "test", "旧消息", "mod"))
        buffer.append(LogRecord(new_time, "INFO", "test", "新消息", "mod"))
        
        # 查询最近1小时
        results = buffer.query(since=time.time() - 3600)
        assert len(results) == 1
        assert results[0]["message"] == "新消息"
    
    def test_query_limit(self):
        buffer = LogBuffer()
        for i in range(50):
            buffer.append(LogRecord(time.time(), "INFO", "test", f"消息{i}", "mod"))
        
        results = buffer.query(limit=10)
        assert len(results) == 10
    
    def test_stats(self):
        buffer = LogBuffer()
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息1", "auth"))
        buffer.append(LogRecord(time.time(), "ERROR", "test", "消息2", "db"))
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息3", "auth"))
        
        stats = buffer.stats()
        assert stats["total_records"] == 3
        assert stats["by_level"]["INFO"] == 2
        assert stats["by_level"]["ERROR"] == 1
        assert stats["oldest_record"] is not None
        assert stats["newest_record"] is not None
    
    def test_stats_empty(self):
        buffer = LogBuffer()
        stats = buffer.stats()
        assert stats["total_records"] == 0
        assert stats["oldest_record"] is None
    
    def test_clear(self):
        buffer = LogBuffer()
        buffer.append(LogRecord(time.time(), "INFO", "test", "消息", "mod"))
        assert len(buffer.query()) == 1
        
        buffer.clear()
        assert len(buffer.query()) == 0
    
    def test_to_dict(self):
        record = LogRecord(
            timestamp=1720000000.0,
            level="WARNING",
            logger_name="silentbook.auth",
            message="登录失败",
            module="auth",
            user_id=123,
            request_id="abc123",
            extra_data={"ip": "1.2.3.4"}
        )
        d = record.to_dict()
        
        assert d["level"] == "WARNING"
        assert d["message"] == "登录失败"
        assert d["user_id"] == 123
        assert d["request_id"] == "abc123"
        assert d["extra"]["ip"] == "1.2.3.4"


# ===== Formatter 测试 =====

class TestStructuredFormatter:
    """测试 JSON 格式化器"""
    
    def test_basic_format(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="测试消息", args=(), exc_info=None
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "测试消息"
        assert "timestamp" in parsed
        assert "logger" in parsed
    
    def test_format_with_request_context(self):
        formatter = StructuredFormatter()
        _request_id_var.set("test-req-123")
        _user_id_var.set(42)
        
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="带上下文的日志", args=(), exc_info=None
        )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert parsed["request_id"] == "test-req-123"
        assert parsed["user_id"] == 42
        
        # Cleanup
        _request_id_var.set(None)
        _user_id_var.set(None)
    
    def test_format_with_extra_fields(self):
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="HTTP请求", args=(), exc_info=None
        )
        record.method = "GET"
        record.path = "/api/users"
        record.status_code = 200
        record.duration_ms = 45.2
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert parsed["method"] == "GET"
        assert parsed["path"] == "/api/users"
        assert parsed["status_code"] == 200
        assert parsed["duration_ms"] == 45.2
    
    def test_format_with_exception(self):
        formatter = StructuredFormatter()
        try:
            raise ValueError("测试异常")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
            record = logging.LogRecord(
                name="test", level=logging.ERROR, pathname="test.py",
                lineno=10, msg="出错了", args=(), exc_info=exc_info
            )
        
        output = formatter.format(record)
        parsed = json.loads(output)
        
        assert "exception" in parsed
        assert "ValueError" in parsed["exception"]


class TestColorFormatter:
    """测试彩色格式化器"""
    
    def test_basic_format(self):
        formatter = ColorFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=10, msg="测试消息", args=(), exc_info=None
        )
        
        output = formatter.format(record)
        # Should contain the message
        assert "测试消息" in output
        # Should contain level
        assert "INFO" in output
    
    def test_format_with_context(self):
        formatter = ColorFormatter()
        _request_id_var.set("abcdef12")
        _user_id_var.set(5)
        
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="test.py",
            lineno=10, msg="警告消息", args=(), exc_info=None
        )
        record.method = "POST"
        record.status_code = 401
        
        output = formatter.format(record)
        assert "req=abcdef12" in output
        assert "user=5" in output
        assert "method=POST" in output
        assert "status_code=401" in output
        
        # Cleanup
        _request_id_var.set(None)
        _user_id_var.set(None)


# ===== BufferHandler 测试 =====

class TestBufferHandler:
    """测试缓冲区 Handler"""
    
    def test_handler_writes_to_buffer(self):
        buffer = LogBuffer(max_size=100)
        handler = BufferHandler(buffer, level=logging.INFO)
        
        logger = logging.getLogger("test.buffer_handler")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        
        logger.info("通过 handler 写入")
        
        results = buffer.query()
        assert len(results) == 1
        assert results[0]["message"] == "通过 handler 写入"
        
        # Cleanup
        logger.removeHandler(handler)
    
    def test_handler_respects_level(self):
        buffer = LogBuffer(max_size=100)
        handler = BufferHandler(buffer, level=logging.WARNING)
        
        logger = logging.getLogger("test.buffer_level")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        
        logger.debug("调试信息")  # Should not be captured
        logger.warning("警告信息")  # Should be captured
        
        results = buffer.query()
        assert len(results) == 1
        assert results[0]["level"] == "WARNING"
        
        logger.removeHandler(handler)


# ===== 工具函数测试 =====

class TestUtilityFunctions:
    """测试工具函数"""
    
    def test_generate_request_id(self):
        rid1 = generate_request_id()
        rid2 = generate_request_id()
        
        assert len(rid1) == 16
        assert len(rid2) == 16
        assert rid1 != rid2
    
    def test_set_request_context(self):
        set_request_context(request_id="test-123", user_id=99)
        
        assert _request_id_var.get() == "test-123"
        assert _user_id_var.get() == 99
        
        # Cleanup
        _request_id_var.set(None)
        _user_id_var.set(None)
    
    def test_get_logger(self):
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        assert isinstance(logger, logging.Logger)


# ===== API 端点测试 =====

class TestLogAPIEndpoints:
    """测试日志管理 API"""
    
    @pytest.fixture
    def client(self):
        """创建测试客户端（SQLite in-memory）"""
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.database import Base, get_db
        from app.main import app
        from app.auth import hash_password
        from app.database import User
        
        # SQLite in-memory
        test_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        
        # SQLite boolean fix
        @event.listens_for(test_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        
        TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        
        # Override DB dependency
        def override_get_db():
            try:
                db = TestSession()
                yield db
            finally:
                db.close()
        
        app.dependency_overrides[get_db] = override_get_db
        
        # Create tables
        Base.metadata.create_all(bind=test_engine)
        
        # Create test user
        db = TestSession()
        user = User(
            email="test@example.com",
            password_hash=hash_password("testpass123"),
            is_active=True
        )
        db.add(user)
        db.commit()
        db.close()
        
        yield TestClient(app)
        
        # Cleanup
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
    
    @pytest.fixture
    def auth_headers(self, client):
        """获取认证头"""
        response = client.post("/auth/login", json={
            "account": "test@example.com",
            "password": "testpass123"
        })
        token = response.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    
    def test_query_logs_unauthorized(self, client):
        """未认证不能查询日志"""
        response = client.get("/admin/logs")
        assert response.status_code == 401
    
    def test_query_logs_authorized(self, client, auth_headers):
        """认证后可以查询日志"""
        # Write some logs first
        logger = logging.getLogger("test.api")
        logger.info("API 测试日志")
        
        response = client.get("/admin/logs", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)
    
    def test_query_logs_with_filters(self, client, auth_headers):
        """测试日志过滤"""
        logger = logging.getLogger("test.filter")
        logger.info("过滤测试 INFO")
        logger.error("过滤测试 ERROR")
        
        response = client.get("/admin/logs?level=ERROR", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        for log in data["logs"]:
            assert log["level"] == "ERROR"
    
    def test_query_logs_search(self, client, auth_headers):
        """测试日志搜索 API 端点正常响应"""
        # Directly inject a record into the buffer for reliable testing
        from app.logging_config import LogRecord
        log_buffer.append(LogRecord(
            timestamp=time.time(),
            level="INFO",
            logger_name="test.search",
            message="searchable-unique-token-xyz",
            module="test"
        ))
        
        response = client.get("/admin/logs?search=searchable-unique-token", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["count"] >= 1
        messages = [log["message"] for log in data["logs"]]
        assert any("searchable-unique-token" in msg for msg in messages)
    
    def test_log_stats_unauthorized(self, client):
        """未认证不能查看统计"""
        response = client.get("/admin/logs/stats")
        assert response.status_code == 401
    
    def test_log_stats_authorized(self, client, auth_headers):
        """认证后可以查看统计"""
        response = client.get("/admin/logs/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_records" in data
        assert "max_capacity" in data
        assert "by_level" in data
        assert "by_module" in data
    
    def test_clear_logs(self, client, auth_headers):
        """测试清空日志"""
        # Write some logs
        logger = logging.getLogger("test.clear")
        logger.info("待清空日志")
        
        # Clear
        response = client.post("/admin/logs/clear", headers=auth_headers)
        assert response.status_code == 200
        
        # Verify empty
        response = client.get("/admin/logs", headers=auth_headers)
        data = response.json()
        assert data["count"] == 0


# ===== 集成测试 =====

class TestLoggingIntegration:
    """测试日志系统集成"""
    
    def test_setup_logging_creates_handlers(self):
        """setup_logging 应该添加 handlers"""
        import os
        original_level = os.environ.get("LOG_LEVEL")
        original_dir = os.environ.get("LOG_DIR")
        
        os.environ["LOG_LEVEL"] = "DEBUG"
        os.environ["LOG_DIR"] = "/tmp/silentbook-test-logs"
        
        try:
            setup_logging()
            root = logging.getLogger()
            
            # Should have at least console + buffer handlers
            assert len(root.handlers) >= 2
            
            # Check buffer handler exists
            has_buffer = any(isinstance(h, BufferHandler) for h in root.handlers)
            assert has_buffer
            
        finally:
            # Cleanup
            if original_level:
                os.environ["LOG_LEVEL"] = original_level
            elif "LOG_LEVEL" in os.environ:
                del os.environ["LOG_LEVEL"]
            
            if original_dir:
                os.environ["LOG_DIR"] = original_dir
            elif "LOG_DIR" in os.environ:
                del os.environ["LOG_DIR"]
            
            # Clear handlers
            root = logging.getLogger()
            root.handlers.clear()
    
    def test_log_context_isolation(self):
        """不同请求的上下文应该隔离"""
        import threading
        
        results = {}
        
        def worker(name, req_id, user_id):
            set_request_context(request_id=req_id, user_id=user_id)
            time.sleep(0.01)  # Simulate work
            results[name] = {
                "request_id": _request_id_var.get(),
                "user_id": _user_id_var.get()
            }
            _request_id_var.set(None)
            _user_id_var.set(None)
        
        t1 = threading.Thread(target=worker, args=("t1", "req-1", 1))
        t2 = threading.Thread(target=worker, args=("t2", "req-2", 2))
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert results["t1"]["request_id"] == "req-1"
        assert results["t1"]["user_id"] == 1
        assert results["t2"]["request_id"] == "req-2"
        assert results["t2"]["user_id"] == 2

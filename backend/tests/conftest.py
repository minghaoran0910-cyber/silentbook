"""全量运行时测试隔离：每个用例前后快照并恢复 app 级全局状态。

背景：30+ 测试文件各自挂 app.dependency_overrides[get_db] 指向自己的
内存 engine，单文件跑全绿，但全量跑时上一个文件的 override 泄漏到下一个
文件（no such table / 409 该邮箱已注册）。本 fixture 做快照恢复，
单文件行为不受影响。
"""
import pytest

import app.main as main_mod
from app.main import app


@pytest.fixture(autouse=True)
def _isolate_app_globals():
    overrides_snapshot = dict(app.dependency_overrides)
    rate_limit_snapshot = main_mod.RATE_LIMIT_ENABLED
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides.update(overrides_snapshot)
    main_mod.RATE_LIMIT_ENABLED = rate_limit_snapshot

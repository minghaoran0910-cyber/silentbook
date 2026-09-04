import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from ..database import Account, Setting, WebhookEvent
from ..notification_push import pusher

logger = logging.getLogger("silentbook")

ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
AGENT_API_URL = os.getenv("AGENT_API_URL", "http://localhost:5000")
PARSER_API_URL = os.getenv("PARSER_API_URL", "http://localhost:6000")

# ===== API 限流配置 =====
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "100"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))  # seconds
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


PLATFORM_ACCOUNT_MAP = {
    "cmb": "招商银行", "icbc": "工商银行", "ccb": "建设银行",
    "abc": "农业银行", "boc": "中国银行",
    "bocom": "交通银行", "spdb": "浦发银行",
    "ceb": "光大银行", "citic": "中信银行",
    "unionpay": "云闪付",
    "alipay": "支付宝", "wechat_pay": "微信", "wechat": "微信",
    "meituan": "美团", "jd": "京东", "taobao": "淘宝",
    "cash": "现金",
}


def normalize_account_name(account_name: str) -> str:
    """账户命名空间统一为中文名：解析器/手动/导入三路入口在此归一，
    避免同一账户存成 cmb 与 招商银行 两份。"""
    if not account_name:
        return account_name
    return PLATFORM_ACCOUNT_MAP.get(account_name, account_name)

def _update_account_balance(db: Session, account_name: str, transaction_type: str, amount: float, reverse: bool = False) -> Optional[float]:
    """联动更新账户余额。reverse=True 表示回滚（删除/更新时先用）。返回更新后余额，账户不存在返回None。"""
    if not account_name:
        return None
    # 规范化：解析器返回的平台标识映射到账户表中文名
    normalized = PLATFORM_ACCOUNT_MAP.get(account_name, account_name)
    account = db.query(Account).filter(Account.name == normalized).first()
    if not account:
        return None
    delta = amount
    if transaction_type == 'expense':
        delta = -amount
    if reverse:
        delta = -delta
    account.balance = (account.balance or 0) + delta
    account.updated_at = datetime.utcnow()
    return float(account.balance)


# IMP-040: 低余额主动告警阈值
LOW_BALANCE_THRESHOLD = 100.0  # 余额低于此值触发告警


async def _check_low_balance_alert(account_name: str, new_balance: float, tx_amount: float, tx_type: str):
    """IMP-040: 支出后余额低于阈值时主动告警。仅对支出交易触发。"""
    if new_balance is None or tx_type != 'expense':
        return
    if new_balance >= LOW_BALANCE_THRESHOLD:
        return
    normalized = PLATFORM_ACCOUNT_MAP.get(account_name, account_name)
    title = f"🔴 低余额告警：{normalized}"
    content = (
        f"**账户**: {normalized}\n"
        f"**当前余额**: ¥{new_balance:.2f}\n"
        f"**本次支出**: ¥{tx_amount:.2f}\n"
        f"**告警阈值**: ¥{LOW_BALANCE_THRESHOLD:.0f}\n\n"
        f"⚠️ 余额已低于¥{LOW_BALANCE_THRESHOLD:.0f}，请及时充值！"
    )
    logger.warning(f"IMP-040 低余额告警: {normalized} 余额¥{new_balance:.2f} < ¥{LOW_BALANCE_THRESHOLD:.0f}")
    try:
        await pusher.push_to_feishu(title, content)
    except Exception as e:
        logger.error(f"IMP-040 飞书推送失败: {e}")
    try:
        await pusher.push_to_wechat(title, content)
    except Exception as e:
        logger.error(f"IMP-040 微信推送失败: {e}")


def _webhook_item_hash(title: str, body: str, source: str, timestamp: Optional[str]) -> str:
    """业务级去重键：对规范 JSON 算 sha256，同一条通知换 event_id 重试也能识别。"""
    canonical = json.dumps(
        {
            "title": title or "",
            "body": body or "",
            "source": source or "",
            "timestamp": timestamp or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_duplicate_body(db: Session, body_hash: str) -> bool:
    """检查 body_hash 是否已入账。存量库（未执行迁移）缺列时降级为不去重并记日志。"""
    try:
        return (
            db.query(WebhookEvent).filter(WebhookEvent.body_hash == body_hash).first()
            is not None
        )
    except OperationalError:
        logger.warning("webhook_events.body_hash 列缺失（未执行迁移），本次跳过业务去重")
        return False


def _is_placeholder_analysis(result: dict) -> bool:
    """Agent 返回占位警告（未配置 Key/服务不可用）时不入库，避免污染分析历史。"""
    texts = [result.get(t, "") or "" for t in ("consumption", "investment", "suggestion")]
    if not texts[0]:
        return False
    return all(("未配置" in t or "暂不可用" in t or "请检查" in t) for t in texts)


# ===== 五级预警阈值 (V2-007) =====
# 五级预警：安全/正常/提醒/超支/严重超支
# 每级定义：级别、名称、颜色、usage上界（小数）
ALERT_LEVELS = [
    {"level": 1, "name": "安全",     "color": "green",  "max": 0.5},
    {"level": 2, "name": "正常",     "color": "blue",   "max": 0.8},
    {"level": 3, "name": "提醒",     "color": "yellow", "max": 1.0},
    {"level": 4, "name": "超支",     "color": "orange", "max": 1.2},
    {"level": 5, "name": "严重超支", "color": "red",    "max": float('inf')},
]

# 默认预警阈值列表（可被预算级自定义覆盖）
DEFAULT_ALERT_THRESHOLDS = [0.5, 0.8, 1.0, 1.2]


def get_alert_level(usage_rate: float, custom_thresholds: list = None) -> dict:
    """根据使用率返回预警级别。usage_rate 是小数（0.85 = 85%）。"""
    thresholds = custom_thresholds if custom_thresholds and len(custom_thresholds) == 4 else DEFAULT_ALERT_THRESHOLDS
    for i, t in enumerate(thresholds):
        if usage_rate < t:
            return ALERT_LEVELS[i]
    return ALERT_LEVELS[4]


LEVEL_LABELS = {
    "L1": "必要支出",
    "L2": "改善支出",
    "L3": "非必要支出",
}

LEVEL_COMPRESSIBILITY = {
    "L1": "<10%",
    "L2": "30-50%",
    "L3": "80-100%",
}

# 默认分类→级别映射（用户可覆盖）
DEFAULT_CATEGORY_LEVELS = {
    # L1 必要
    "房租": "L1", "水电": "L1", "燃气": "L1", "物业": "L1",
    "餐饮": "L1", "主食": "L1", "买菜": "L1", "外卖": "L1",
    "交通": "L1", "地铁": "L1", "公交": "L1", "打车": "L1", "停车": "L1",
    "话费": "L1", "网费": "L1", "保险": "L1", "医疗": "L1",
    "日用": "L1", "母婴": "L1", "生活": "L1",
    "水电燃气": "L1", "政务缴纳": "L1", "住房": "L1",
    # L2 改善
    "健身": "L2", "学习": "L2", "课程": "L2", "书籍": "L2",
    "社交": "L2", "聚餐": "L2", "礼物": "L2", "理发": "L2",
    "咖啡": "L2", "水果": "L2", "零食": "L2",
    "订阅": "L2", "会员": "L2", "软件": "L2", "金融": "L2",
    "通讯": "L2", "教育": "L2", "投资": "L2",
    # L3 非必要
    "娱乐": "L3", "游戏": "L3", "电影": "L3", "演出": "L3",
    "购物": "L3", "服饰": "L3", "电子": "L3", "数码": "L3",
    "旅游": "L3", "酒店": "L3", "机票": "L3",
    "彩票": "L3", "赌博": "L3",
}

def get_category_level(category: str, db) -> str:
    """获取分类对应的预算级别：优先查预算配置，其次用默认映射，默认L2"""
    import json
    raw = db.query(Setting).filter(Setting.key == "budgets").first()
    if raw and raw.value:
        budgets = json.loads(raw.value)
        for b in budgets:
            if b.get("category") == category and "level" in b:
                return b["level"]
    return DEFAULT_CATEGORY_LEVELS.get(category, "L2")


OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:18789")

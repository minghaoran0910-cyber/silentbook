from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
import re
from datetime import datetime
from .notification_filter import is_financial_notification

app = FastAPI(title="SilentBook Notification Parser", version="0.3.0")


class NotificationRequest(BaseModel):
    title: str
    body: str
    source: Optional[str] = None
    timestamp: Optional[str] = None


class ParsedTransaction(BaseModel):
    amount: float
    category: str
    account: str
    description: str
    transaction_type: str  # income/expense
    raw_text: str
    confidence: float  # 0-1, 解析置信度
    parsed_at: str
    bank_card: Optional[str] = None  # 银行卡号后四位
    balance: Optional[float] = None  # 余额
    merchant: Optional[str] = None  # 商户名


# ---------------------------------------------------------------------------
# 银行/支付平台配置
# ---------------------------------------------------------------------------

PLATFORM_PATTERNS = {
    "cmb": {  # 招商银行
        "keywords": ["招商银行", "招行", "CMB"],
        "amount_patterns": [
            r"(?:消费|支出|付款|转账|还款|退款|转入|收入)\D*?人民币\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)",
            r"(?:消费|支出|付款|转账|还款|退款|转入|收入)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"人民币\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)\s*元",
            r"[¥￥]\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"(\d{1,10}(?:\.\d{1,2})?)\s*元",
        ],
        "desc_patterns": [
            r"(?:在)\s*(.+?)(?:消费|刷卡|付款)",
            r"商户[：:]\s*(.+?)(?:\s|，|,|$)",
            r"摘要[：:]\s*(.+?)(?:\s|，|,|$)",
        ],
    },
    "icbc": {  # 工商银行
        "keywords": ["工商银行", "工行", "ICBC"],
        "amount_patterns": [
            r"(?:消费|支出|付款|扣款|转入|收入|转出|取款)\D*?人民币\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)",
            r"(?:消费|支出|付款|扣款|转入|收入|转出|取款)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"交易金额[：:]\s*[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"(\d{1,10}(?:\.\d{1,2})?)\s*元",
        ],
        "desc_patterns": [
            r"(?:在|于)\s*(.+?)(?:消费|取款|支付|付款)",
            r"商户[：:]\s*(.+?)(?:\s|，|,|$)",
            r"摘要[：:]\s*(.+?)(?:\s|，|,|$)",
        ],
    },
    "ccb": {  # 建设银行
        "keywords": ["建设银行", "建行", "CCB"],
        "amount_patterns": [
            r"(?:消费|支出|付款|转账|还款|退款|转入|收入)\D*?人民币\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)",
            r"(?:消费|支出|付款|转账|还款|退款|转入|收入)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"金额[：:]\s*[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"(\d{1,10}(?:\.\d{1,2})?)\s*元",
        ],
        "desc_patterns": [
            r"(?:在|向)\s*(.+?)(?:消费|支付|付款)",
            r"商户[：:]\s*(.+?)(?:\s|，|,|$)",
        ],
    },
    "alipay": {  # 支付宝
        "keywords": ["支付宝", "Alipay", "蚂蚁"],
        "amount_patterns": [
            r"(?:付款|消费|支付|转账|收款|退款|充值|提现)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)\s*元",
            r"[¥￥]\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"金额[：:]\s*[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"(\d{1,10}(?:\.\d{1,2})?)\s*元",
        ],
        "desc_patterns": [
            r"(?:在|通过)\s*(.+?)(?:付款|消费|支付|扫码付款)",
            r"商户[：:]\s*(.+?)(?:\s|，|,|$)",
            r"交易对方[：:]\s*(.+?)(?:\s|，|,|$)",
            r"向\s*(.+?)(?:付款|转账|支付)",
        ],
    },
    "wechat_pay": {  # 微信支付
        "keywords": ["微信支付", "WeChat Pay", "微信转账", "微信扫码付"],
        "amount_patterns": [
            r"(?:付款|消费|支付|转账|收款|退款|红包|二维码转账)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)\s*元",
            r"[¥￥]\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"金额[：:]\s*[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
            r"(\d{1,10}(?:\.\d{1,2})?)\s*元",
        ],
        "desc_patterns": [
            r"(?:在|通过)\s*(.+?)(?:付款|消费|支付|扫码付款)",
            r"商户[：:]\s*(.+?)(?:\s|，|,|$)",
            r"交易对方[：:]\s*(.+?)(?:\s|，|,|$)",
            r"向\s*(.+?)(?:付款|转账|支付)",
            r"来自[：:]\s*(.+?)(?:\s|，|,|$)",
        ],
    },
}

# ---------------------------------------------------------------------------
# 分类关键词
# ---------------------------------------------------------------------------

CATEGORY_KEYWORDS = {
    "餐饮": [
        "餐", "饭", "食", "吃", "美团", "饿了么", "肯德基", "麦当劳",
        "星巴克", "瑞幸", "咖啡", "奶茶", "火锅", "烧烤", "外卖",
        "必胜客", "海底捞", "喜茶", "奈雪",
    ],
    "交通": [
        "打车", "滴滴", "地铁", "公交", "加油", "停车", "高速",
        "出租", "高铁", "火车", "机票", "航空", "12306", "曹操",
        "T3出行", "高德打车",
    ],
    "购物": [
        "淘宝", "京东", "拼多多", "天猫", "超市", "商场", "百货",
        "沃尔玛", "盒马", "山姆", "Costco", "便利店", "7-11",
        "全家", "罗森",
    ],
    "娱乐": [
        "电影", "游戏", "KTV", "健身", "运动", "网易云", "QQ音乐",
        "爱奇艺", "腾讯视频", "优酷", "B站", "bilibili", "抖音",
    ],
    "生活": [
        "水电", "物业", "房租", "话费", "流量", "宽带", "燃气",
        "暖气", "电费", "水费",
    ],
    "通讯": [
        "中国移动", "中国联通", "中国电信",
    ],
    "医疗": [
        "医院", "药", "诊所", "体检", "挂号", "门诊",
    ],
    "教育": [
        "学费", "培训", "课程", "书店", "考试",
    ],
    "投资": [
        "基金", "股票", "理财", "定投", "证券",
    ],
    "金融": [
        "保险", "贷款", "利息", "手续费", "年费",
    ],
}


# ---------------------------------------------------------------------------
# Core parsing functions
# ---------------------------------------------------------------------------

def detect_platform(text: str, source: Optional[str] = None) -> str:
    """检测通知来源平台，返回标准化标识"""
    combined = f"{text} {source or ''}".lower()

    for platform, config in PLATFORM_PATTERNS.items():
        for keyword in config["keywords"]:
            if keyword.lower() in combined:
                return platform

    return "unknown"


def extract_amount(text: str, platform: str) -> float:
    """从文本中提取金额"""
    patterns = PLATFORM_PATTERNS.get(platform, {}).get("amount_patterns", [])

    # 通用 fallback 模式
    fallback_patterns = [
        r"(?:消费|支出|付款|扣款|转入|收入|到账|退款|收款|还款|充值|提现|转出|取款)\D*?[¥￥]?\s*(\d{1,10}(?:\.\d{1,2})?)",
        r"[¥￥]\s*(\d{1,10}(?:\.\d{1,2})?)",
        r"(\d{1,10}(?:\.\d{1,2})?)\s*(?:元|块)",
    ]

    all_patterns = patterns + fallback_patterns

    for pattern in all_patterns:
        match = re.search(pattern, text)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
                if amount > 0:
                    return amount
            except ValueError:
                continue

    return 0.0


def extract_description(text: str, platform: str) -> str:
    """提取商户或描述信息"""
    patterns = PLATFORM_PATTERNS.get(platform, {}).get("desc_patterns", [])

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            desc = match.group(1).strip()
            if desc and len(desc) < 50:
                return desc

    return text[:50] if len(text) > 50 else text


def detect_type(text: str) -> str:
    """判断是收入还是支出"""
    # 先检查收入关键词（收入信号更明确，优先匹配）
    income_keywords = [
        "收入", "到账", "转入", "退款", "红包", "收款",
        "回款", "工资", "奖金", "利息", "分红", "报销",
    ]
    for kw in income_keywords:
        if kw in text:
            return "income"

    # 再检查支出
    expense_keywords = [
        "消费", "支出", "付款", "扣款", "转出", "缴费",
        "还款", "充值", "扫码付款", "二维码转账",
    ]
    for kw in expense_keywords:
        if kw in text:
            return "expense"

    return "expense"


def extract_bank_card(text: str) -> Optional[str]:
    """提取银行卡号后四位"""
    patterns = [
        r"尾号\s*(\d{4})",
        r"(?:卡|账户|后四位)[：:\s]*(\d{4})",
        r"(?:\*{4,}|\d{4}\*+\d{4})(\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def extract_balance(text: str) -> Optional[float]:
    """提取余额"""
    patterns = [
        r"(?:余额|可用额度|可用余额|可用)[：:\s]*[¥￥]?\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                return float(amount_str)
            except ValueError:
                continue
    return None


def extract_merchant(text: str, platform: str) -> Optional[str]:
    """提取商户名称"""
    # 先尝试平台特定的 desc patterns
    desc = extract_description(text, platform)
    # 如果 description 看起来像商户名（不是整段文本的截断），就当作商户
    if desc and desc != text[:50] and len(desc) < 50:
        return desc
    return None


def auto_categorize(description: str, full_text: str = "") -> str:
    """根据描述和全文自动分类"""
    combined = f"{description} {full_text}"

    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return category
    return "其他"


def calculate_confidence(amount: float, description: str) -> float:
    """计算解析置信度"""
    confidence = 0.5

    if amount > 0:
        confidence += 0.3
    if description and len(description) > 3:
        confidence += 0.2

    return min(confidence, 1.0)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    return {
        "name": "SilentBook Notification Parser",
        "version": "0.2.0",
        "supported_platforms": list(PLATFORM_PATTERNS.keys()),
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/parse")
async def parse_notification(notification: NotificationRequest):
    """解析银行/支付通知，提取交易信息。

    V2-038: 增加前置过滤，非财务通知直接返回 filtered 结果，不创建交易。
    """
    text = f"{notification.title} {notification.body}"

    # V2-038: 前置过滤非财务通知
    filter_result = is_financial_notification(
        notification.title, notification.body, notification.source
    )
    if not filter_result.is_financial:
        return {
            "filtered": True,
            "filter_reason": filter_result.reason,
            "filter_confidence": filter_result.confidence,
            "amount": 0.0,
            "category": "其他",
            "account": "unknown",
            "transaction_type": "expense",
            "description": "",
            "raw_text": text.strip(),
            "confidence": 0.0,
            "parsed_at": datetime.now().isoformat(),
            "bank_card": None,
            "balance": None,
            "merchant": None,
        }

    platform = detect_platform(text, notification.source)
    amount = extract_amount(text, platform)
    tx_type = detect_type(text)
    description = extract_description(text, platform)
    category = auto_categorize(description, text)
    confidence = calculate_confidence(amount, description)
    bank_card = extract_bank_card(text)
    balance = extract_balance(text)
    merchant = extract_merchant(text, platform)

    return {
        "filtered": False,
        "filter_reason": filter_result.reason,
        "filter_confidence": filter_result.confidence,
        "amount": amount,
        "category": category,
        "account": platform,
        "description": description,
        "transaction_type": tx_type,
        "raw_text": text.strip(),
        "confidence": confidence,
        "parsed_at": datetime.now().isoformat(),
        "bank_card": bank_card,
        "balance": balance,
        "merchant": merchant,
    }


@app.post("/parse/batch")
async def parse_batch(notifications: List[NotificationRequest]):
    """批量解析通知"""
    results = []
    filtered_count = 0
    for notification in notifications:
        result = await parse_notification(notification)
        results.append(result)
        if result.get("filtered"):
            filtered_count += 1
    return {
        "count": len(results),
        "filtered_count": filtered_count,
        "financial_count": len(results) - filtered_count,
        "transactions": results,
    }


@app.get("/platforms")
async def list_platforms():
    """列出支持的平台和分类"""
    return {
        "platforms": list(PLATFORM_PATTERNS.keys()),
        "categories": list(CATEGORY_KEYWORDS.keys()),
    }

"""
通知过滤器 - 白名单模式

V2-039: 只认真实交易通知，必须同时满足三条：
1. 来源白名单（支付渠道/电商/生活服务/信贷/银行/其他）
2. 动作白名单（扣款/收入/付款/支付/转账/还款/退款/消费/支出）
3. 必须有明确金额（正则匹配）

不符合以上三条 → 不记录，没有任何例外
"""
import re
from typing import Optional


# ---------------------------------------------------------------------------
# 来源白名单
# ---------------------------------------------------------------------------

SOURCE_WHITELIST = [
    # 支付渠道
    "微信支付", "WeChat Pay", "微信扫码付", "微信转账",
    "支付宝", "Alipay", "蚂蚁",
    "Apple Pay", "云闪付", "UnionPay",
    # 电商平台
    "淘宝", "天猫", "京东", "拼多多", "抖音", "小红书",
    # 生活服务
    "美团", "饿了么", "滴滴", "高德", "哈啰",
    # 信贷产品
    "白条", "花呗", "借呗", "信用卡",
    # 银行（所有银行关键词）
    "招商银行", "工商银行", "建设银行", "农业银行", "交通银行",
    "邮储银行", "民生银行", "兴业银行", "浦发银行", "中信银行",
    "光大银行", "平安银行", "华夏银行", "广发银行", "北京银行",
    "宁波银行", "杭州银行", "南京银行", "上海银行",
    "招商银行", "工行", "建行", "农行", "交行", "邮储",
    "CMB", "ICBC", "CCB", "ABC", "BOC",
    # 其他
    "App Store", "Google Play", "Steam",
    # 通用银行关键词
    "银行", "Bank",
]

# ---------------------------------------------------------------------------
# 动作白名单
# ---------------------------------------------------------------------------

ACTION_WHITELIST = [
    "扣款", "收入", "付款", "支付", "转账",
    "还款", "退款", "消费", "支出",
    "到账", "收款", "充值", "提现", "扫码付款",
    "转入", "转出", "取款",
]

# ---------------------------------------------------------------------------
# 黑名单（优先级高于白名单，命中即过滤）
# 解决：账单通知包含"还款日""应还"等非交易动作被误判为交易
# ---------------------------------------------------------------------------

BLACKLIST_PHRASES = [
    "账单已生成", "账单日", "还款日", "到期还款日", "最后还款日",
    "应还金额", "最低还款", "本期应还", "未出账单",
    "额度调整", "提额", "临时额度",
    "积分", "权益", "活动规则",
    "快递签收", "已签收", "派送中", "已揽收",
    "登录提醒", "验证码", "密码错误",
    "系统升级", "维护通知",
    # 营销/优惠券/红包（非真实交易）
    "优惠券", "红包已到账", "满减", "折扣", "促销", "限时",
    "已到账，满", "券已到账", "现金红包", "新人专享",
    "周报", "月报", "日报", "周报已生成",
]

# ---------------------------------------------------------------------------
# 金额正则（必须有明确金额）
# ---------------------------------------------------------------------------

AMOUNT_PATTERN = r"[¥￥]?\s*(\d{1,10}(?:,\d{3})*(?:\.\d{1,2})?)\s*元"
AMOUNT_FALLBACK = r"[¥￥]\s*(\d{1,10}(?:\.\d{1,2})?)"


class FilterResult:
    """过滤结果"""
    def __init__(self, is_financial: bool, reason: str = "", confidence: float = 0.0):
        self.is_financial = is_financial
        self.reason = reason
        self.confidence = confidence

    def to_dict(self):
        return {
            "is_financial": self.is_financial,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def _check_source_whitelist(text: str) -> bool:
    """检查是否匹配来源白名单"""
    text_lower = text.lower()
    for keyword in SOURCE_WHITELIST:
        if keyword.lower() in text_lower:
            return True
    return False


def _check_action_whitelist(text: str) -> bool:
    """检查是否匹配动作白名单"""
    for action in ACTION_WHITELIST:
        if action in text:
            return True
    return False


def _check_amount(text: str) -> bool:
    """检查是否有明确金额"""
    if re.search(AMOUNT_PATTERN, text):
        return True
    if re.search(AMOUNT_FALLBACK, text):
        return True
    return False


def is_financial_notification(title: str, body: str, source: Optional[str] = None) -> FilterResult:
    """
    白名单模式：必须同时满足三条才判定为财务通知
    
    1. 来源白名单
    2. 动作白名单
    3. 必须有明确金额
    
    不符合 → 不记录，没有任何例外
    """
    text = f"{title} {body}".strip()
    
    # 黑名单优先：命中即过滤，无论白名单是否满足
    for phrase in BLACKLIST_PHRASES:
        if phrase in text:
            return FilterResult(
                is_financial=False,
                reason=f"黑名单命中: {phrase}",
                confidence=0.95,
            )
    
    # 三条必须同时满足
    has_source = _check_source_whitelist(text)
    has_action = _check_action_whitelist(text)
    has_amount = _check_amount(text)
    
    # 全部满足 → 财务通知
    if has_source and has_action and has_amount:
        return FilterResult(
            is_financial=True,
            reason="白名单三条全满足: 来源+动作+金额",
            confidence=0.95,
        )
    
    # 不满足，给出原因
    reasons = []
    if not has_source:
        reasons.append("来源不在白名单")
    if not has_action:
        reasons.append("无交易动作")
    if not has_amount:
        reasons.append("无明确金额")
    
    return FilterResult(
        is_financial=False,
        reason="白名单未通过: " + ", ".join(reasons),
        confidence=0.9,
    )

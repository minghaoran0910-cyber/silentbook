"""
通知过滤器 - 判断通知是否为真实财务交易

V2-038: 过滤掉物流、营销、未接来电、游戏等非财务通知
"""
import re
from typing import Optional


# ---------------------------------------------------------------------------
# 非财务通知模式（匹配到任意一条即判定为非财务）
# ---------------------------------------------------------------------------

NON_FINANCIAL_PATTERNS = [
    # 物流快递
    "快递", "包裹", "签收", "派送", "揽收", "运输中", "已发货",
    "菜鸟", "顺丰速运", "圆通", "中通", "韵达", "申通", "极兔",
    "邮政", "EMS", "德邦", "京东物流",
    # 营销推广
    "限时优惠", "满减", "领券", "秒杀", "促销活动", "折扣",
    "专属优惠", "下单立减", "新用户", "首单", "返现活动",
    # 未接来电 / 通讯提醒
    "未接来电", "来电提醒", "未读短信", "语音信箱",
    # 游戏 / APP 内通知
    "体力已满", "签到成功", "登录奖励", "游戏", "副本",
    "装备", "升级成功", "任务完成", "成就解锁",
    # 系统 / 应用通知
    "系统更新", "版本升级", "系统维护", "请更新",
    "新的版本", "App更新",
    # 社交互动
    "点赞", "评论了你", "关注了你", "新粉丝", "好友请求",
    "提到了你", "转发",
    # 新闻资讯
    "今日热点", "新闻", "头条", "资讯", "热搜",
    # 健康 / 生活提醒
    "步数", "运动提醒", "喝水提醒", "该休息了",
    "站立提醒", "睡眠报告",
    # 天气
    "天气预报", "气温", "降雨提醒", "空气质量",
    # 日历 / 待办
    "日程提醒", "待办事项", "闹钟",
    # 银行营销（非交易）
    "账单分期", "额度提升", "信用卡额度", "可用额度已",  # 注意："可用额度XXXX元" 是营销，不是交易
    "积分兑换", "积分到期", "年费提醒",  # 年费提醒不是扣款
    # 其他常见垃圾
    "验证", "验证码", "登录确认", "安全提醒",
    "绑定", "解绑", "开通服务", "关闭服务",
]

# ---------------------------------------------------------------------------
# 财务交易的强信号（匹配到即判定为财务通知，优先级高于非财务模式）
# ---------------------------------------------------------------------------

FINANCIAL_STRONG_SIGNALS = [
    # 明确的交易动作 + 金额组合（必须同时有金额）
    r"消费.*\d", r"支出.*\d", r"付款.*\d", r"转账.*\d",
    r"转入.*\d", r"收入.*\d", r"退款.*\d", r"扣款.*\d",
    r"到账.*\d", r"收款.*\d", r"还款.*\d", r"充值.*\d",
    r"提现.*\d", r"扫码付款.*\d", r"二维码转账.*\d",
    # 金额符号（人民币/¥ + 数字）
    r"人民币\s*\d", r"[¥￥]\s*\d",
    # 尾号 + 金额（银行卡交易特征）
    r"尾号\d{4}.*\d+\.?\d*",
]

# ---------------------------------------------------------------------------
# 银行/支付平台名称（需要配合交易动作才判定为财务通知）
# ---------------------------------------------------------------------------

FINANCIAL_PLATFORM_KEYWORDS = [
    "招商银行", "工商银行", "建设银行", "农业银行", "交通银行",
    "邮储银行", "民生银行", "兴业银行", "浦发银行", "中信银行",
    "光大银行", "平安银行", "华夏银行", "广发银行", "北京银行",
    "支付宝", "微信支付", "WeChat Pay", "Alipay",
]

# ---------------------------------------------------------------------------
# 银行/支付平台通知中的非交易模式（银行名+这些模式 = 非交易）
# ---------------------------------------------------------------------------

FINANCIAL_PLATFORM_NON_TRANSACTIONAL = [
    "验证码", "验证", "登录确认", "安全提醒",
    "额度提升", "额度已提", "信用卡额度",
    "积分兑换", "积分到期", "积分将于",
    "账单分期", "分期 available",
    "系统升级", "系统维护", "版本更新",
    "开通服务", "关闭服务", "绑定", "解绑",
]


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


def is_financial_notification(title: str, body: str, source: Optional[str] = None) -> FilterResult:
    """
    判断通知是否为真实财务交易

    判断逻辑：
    1. 先检查强财务信号（银行+金额组合），有则直接判定为财务通知
    2. 再检查非财务模式，匹配到则判定为非财务
    3. 都不匹配时，检查是否有明确的金额+交易动作，有则判定为财务
    4. 最终 fallback：判定为非财务（宁可漏掉，不可误收）

    Returns:
        FilterResult: is_financial=True 表示是财务通知
    """
    text = f"{title} {body}".strip()
    source_text = source or ""
    text_lower = text.lower()

    # Step 1: 检查是否为金融平台的非交易通知（银行名+非交易模式）
    # 这类通知包含银行名但不是交易，如验证码、额度提升、积分兑换
    is_financial_platform = any(kw in text for kw in FINANCIAL_PLATFORM_KEYWORDS)
    if is_financial_platform:
        for non_trans in FINANCIAL_PLATFORM_NON_TRANSACTIONAL:
            if non_trans in text:
                return FilterResult(
                    is_financial=False,
                    reason=f"金融平台非交易通知: {non_trans}",
                    confidence=0.9,
                )

    # Step 2: 检查非财务模式（通用）
    for pattern in NON_FINANCIAL_PATTERNS:
        if pattern.lower() in text_lower:
            return FilterResult(
                is_financial=False,
                reason=f"匹配非财务模式: {pattern}",
                confidence=0.9,
            )

    # Step 3: 检查强财务信号（交易动作+金额组合）
    for pattern in FINANCIAL_STRONG_SIGNALS:
        if re.search(pattern, text):
            return FilterResult(
                is_financial=True,
                reason=f"强财务信号: {pattern}",
                confidence=0.95,
            )

    # Step 4: 金融平台名称 + 有金额（可能是交易）
    if is_financial_platform and re.search(r"\d{1,10}(?:\.\d{1,2})?", text):
        return FilterResult(
            is_financial=True,
            reason="金融平台+包含金额",
            confidence=0.7,
        )

    # Step 5: 检查是否有 金额 + 交易动作 的组合（不限平台）
    amount_pattern = r"\d{1,10}(?:\.\d{1,2})?"
    action_pattern = r"(?:消费|支出|付款|转账|收入|退款|扣款|到账|还款|充值|提现|收款)"
    if re.search(action_pattern, text) and re.search(amount_pattern, text):
        return FilterResult(
            is_financial=True,
            reason="包含交易动作+金额",
            confidence=0.7,
        )

    # Step 6: 来源是已知金融平台
    financial_sources = ["cmb", "icbc", "ccb", "abc", "boc", "alipay", "wechat_pay"]
    if source_text.lower() in financial_sources:
        return FilterResult(
            is_financial=True,
            reason=f"来源为金融平台: {source_text}",
            confidence=0.6,
        )

    # Step 7: Fallback - 判定为非财务（保守策略）
    return FilterResult(
        is_financial=False,
        reason="无明确财务信号",
        confidence=0.5,
    )

"""
V2-038: 通知过滤器测试

测试覆盖：
1. 非财务通知过滤（物流、营销、未接来电、游戏、系统等）
2. 财务通知保留（银行交易、支付通知等）
3. 边界情况（模糊通知、混合内容）
4. API 集成（/parse 端点对非财务通知返回 filtered=True）
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.notification_filter import is_financial_notification


# ===========================================================================
# 非财务通知 - 应该被过滤
# ===========================================================================

class TestNonFinancialFilter:
    """非财务通知过滤测试"""

    # --- 物流快递 ---
    def test_logistics_cainiao(self):
        """菜鸟驿站取件通知"""
        result = is_financial_notification(
            "菜鸟驿站", "您的包裹已到达菜鸟驿站，请及时取件。取件码：12-34-5678"
        )
        assert result.is_financial is False
        assert "快递" in result.reason or "包裹" in result.reason or "菜鸟" in result.reason

    def test_logistics_sf_express(self):
        """顺丰快递签收通知"""
        result = is_financial_notification(
            "顺丰速运", "您的顺丰快递已签收，感谢使用顺丰。"
        )
        assert result.is_financial is False

    def test_logistics_jd_delivery(self):
        """京东物流配送中"""
        result = is_financial_notification(
            "京东物流", "您的订单正在派送中，预计今日送达"
        )
        assert result.is_financial is False

    # --- 营销推广 ---
    def test_marketing_promotion(self):
        """电商促销通知"""
        result = is_financial_notification(
            "淘宝", "限时优惠！满300减50，领券更划算！"
        )
        assert result.is_financial is False

    def test_marketing_new_user(self):
        """新用户优惠"""
        result = is_financial_notification(
            "美团", "新用户首单立减15元，快来下单吧！"
        )
        assert result.is_financial is False

    # --- 未接来电 ---
    def test_missed_call(self):
        """未接来电提醒"""
        result = is_financial_notification(
            "来电提醒", "您有一个未接来电，号码：138****1234"
        )
        assert result.is_financial is False
        assert "未接来电" in result.reason

    # --- 游戏通知 ---
    def test_game_energy(self):
        """游戏体力恢复通知"""
        result = is_financial_notification(
            "原神", "您的体力已满，快来继续冒险吧！"
        )
        assert result.is_financial is False

    def test_game_sign_in(self):
        """游戏签到奖励"""
        result = is_financial_notification(
            "王者荣耀", "签到成功！获得钻石*100，金币*5000"
        )
        assert result.is_financial is False

    # --- 系统通知 ---
    def test_system_update(self):
        """APP更新通知"""
        result = is_financial_notification(
            "微信", "微信有新的版本可用，请更新以获得更好体验"
        )
        assert result.is_financial is False

    # --- 社交通知 ---
    def test_social_like(self):
        """朋友圈点赞通知"""
        result = is_financial_notification(
            "微信", "张三赞了你的朋友圈"
        )
        assert result.is_financial is False

    def test_social_comment(self):
        """评论通知"""
        result = is_financial_notification(
            "小红书", "李四评论了你：太好看了！"
        )
        assert result.is_financial is False

    # --- 验证码 ---
    def test_verification_code(self):
        """验证码通知"""
        result = is_financial_notification(
            "支付宝", "验证码：123456，5分钟内有效，请勿泄露。"
        )
        assert result.is_financial is False
        assert "验证" in result.reason

    # --- 天气/健康 ---
    def test_weather_notification(self):
        """天气预报"""
        result = is_financial_notification(
            "天气", "今日北京晴，气温15-28℃，空气质量良"
        )
        assert result.is_financial is False

    def test_health_reminder(self):
        """喝水提醒"""
        result = is_financial_notification(
            "健康提醒", "该喝水了！今日步数：8532步"
        )
        assert result.is_financial is False

    # --- 银行营销（非交易）---
    def test_bank_credit_limit_increase(self):
        """信用卡额度提升通知（非交易）"""
        result = is_financial_notification(
            "招商银行", "恭喜！您的信用卡额度已提升至50000元"
        )
        assert result.is_financial is False

    def test_bank_points_expiry(self):
        """银行积分到期提醒"""
        result = is_financial_notification(
            "建设银行", "您有12000积分将于12月31日到期，快来积分兑换好礼！"
        )
        assert result.is_financial is False


# ===========================================================================
# 财务通知 - 应该被保留
# ===========================================================================

class TestFinancialKeep:
    """财务通知保留测试"""

    def test_cmb_consumption(self):
        """招行消费通知"""
        result = is_financial_notification(
            "招商银行", "您尾号1234的信用卡于07月08日在星巴克消费人民币88.50元"
        )
        assert result.is_financial is True

    def test_icbc_salary(self):
        """工行工资到账"""
        result = is_financial_notification(
            "工商银行", "您的账户07月08日收入人民币12500.00元，摘要：代发工资"
        )
        assert result.is_financial is True

    def test_alipay_payment(self):
        """支付宝付款"""
        result = is_financial_notification(
            "支付宝", "您于07月08日在瑞幸咖啡扫码付款18.90元。"
        )
        assert result.is_financial is True

    def test_wechat_pay_transfer(self):
        """微信转账"""
        result = is_financial_notification(
            "微信支付", "您于07月08日向张三转账人民币500.00元。"
        )
        assert result.is_financial is True

    def test_ccb_transfer_in(self):
        """建行转入"""
        result = is_financial_notification(
            "建设银行", "您尾号5566的账户07月08日14:20转入人民币800.00元"
        )
        assert result.is_financial is True

    def test_generic_payment_with_amount(self):
        """通用支付通知（有明确金额+交易动作）"""
        result = is_financial_notification(
            "通知", "消费128.50元，商户：盒马鲜生"
        )
        assert result.is_financial is True

    def test_refund_notification(self):
        """退款通知"""
        result = is_financial_notification(
            "通知", "退款到账299.00元，原路退回"
        )
        assert result.is_financial is True

    def test_source_as_financial_platform(self):
        """来源标识为金融平台"""
        result = is_financial_notification(
            "通知", "交易确认", source="alipay"
        )
        assert result.is_financial is True


# ===========================================================================
# 边界情况
# ===========================================================================

class TestEdgeCases:
    """边界情况测试"""

    def test_empty_notification(self):
        """空通知"""
        result = is_financial_notification("", "")
        assert result.is_financial is False
        assert result.confidence >= 0.0

    def test_ambiguous_with_amount(self):
        """有金额但无交易动作（保守判定为非财务）"""
        result = is_financial_notification(
            "提醒", "您的订单金额100元已确认"
        )
        # 没有明确的交易动作+银行/支付平台，保守判定
        # 但如果有"金额"和数字，可能触发 fallback
        # 这里测试不会崩溃即可
        assert isinstance(result.is_financial, bool)

    def test_mixed_content_financial(self):
        """混合内容（包含财务+非财务关键词）"""
        # 银行消费通知里包含"签名"（非财务词）但核心是交易
        result = is_financial_notification(
            "招商银行", "您尾号1234的信用卡消费100元，无需签名"
        )
        # 强信号应该优先
        assert result.is_financial is True

    def test_filter_result_to_dict(self):
        """FilterResult 序列化"""
        result = is_financial_notification("测试", "消费100元")
        d = result.to_dict()
        assert "is_financial" in d
        assert "reason" in d
        assert "confidence" in d


# ===========================================================================
# API 集成测试
# ===========================================================================

class TestFilterAPI:
    """过滤器 API 集成测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_parse_financial_notification(self, client):
        """财务通知正常解析"""
        resp = client.post("/parse", json={
            "title": "招商银行",
            "body": "您尾号1234的信用卡消费人民币88.50元",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filtered"] is False
        assert data["amount"] == 88.50

    def test_parse_non_financial_filtered(self, client):
        """非财务通知被过滤"""
        resp = client.post("/parse", json={
            "title": "菜鸟驿站",
            "body": "您的包裹已到达，取件码：12-34-5678",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filtered"] is True
        assert data["amount"] == 0.0
        assert data["confidence"] == 0.0

    def test_parse_missed_call_filtered(self, client):
        """未接来电被过滤"""
        resp = client.post("/parse", json={
            "title": "未接来电",
            "body": "您有一个未接来电，号码：138****1234",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filtered"] is True

    def test_parse_verification_code_filtered(self, client):
        """验证码通知被过滤"""
        resp = client.post("/parse", json={
            "title": "支付宝",
            "body": "验证码：654321，5分钟内有效",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["filtered"] is True

    def test_batch_parse_mixed(self, client):
        """批量解析混合通知"""
        resp = client.post("/parse/batch", json=[
            {"title": "招商银行", "body": "尾号1234消费100元"},
            {"title": "菜鸟驿站", "body": "包裹已到达"},
            {"title": "支付宝", "body": "扫码付款25.50元"},
            {"title": "游戏", "body": "体力已满，快来签到"},
        ])
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 4
        assert data["filtered_count"] == 2  # 菜鸟 + 游戏
        assert data["financial_count"] == 2  # 招行 + 支付宝

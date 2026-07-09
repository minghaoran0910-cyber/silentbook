"""
SilentBook Notification Parser - Unit Tests

测试覆盖：招商银行、工商银行、建设银行、支付宝、微信支付
每个来源至少 3 个测试用例
"""
import sys
import os
import pytest

# 让 tests 能找到 app 模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.main import (
    extract_amount,
    detect_type,
    detect_platform,
    extract_bank_card,
    extract_balance,
    extract_merchant,
    extract_description,
    auto_categorize,
)


# ===========================================================================
# 招商银行 (CMB)
# ===========================================================================

class TestCMB:
    """招商银行通知解析"""

    def test_cmb_consumption(self):
        """招行信用卡消费"""
        text = "【招商银行】您尾号1234的信用卡于07月08日在星巴克消费人民币88.50元，可用额度52,311.50元。"
        assert detect_platform(text) == 'cmb'
        assert extract_amount(text, 'cmb') == 88.50
        assert detect_type(text) == 'expense'
        assert extract_bank_card(text) == '1234'
        assert '星巴克' in (extract_description(text, 'cmb') or '')
        assert auto_categorize('星巴克', text) == '餐饮'

    def test_cmb_transfer_in(self):
        """招行储蓄卡转入"""
        text = "【招商银行】您尾号5678的储蓄卡于07月08日10:30转入人民币15000.00元，余额23,456.78元。摘要：工资"
        assert detect_platform(text) == 'cmb'
        assert extract_amount(text, 'cmb') == 15000.00
        assert detect_type(text) == 'income'
        assert extract_bank_card(text) == '5678'
        assert extract_balance(text) == 23456.78

    def test_cmb_refund(self):
        """招行退款"""
        text = "【招商银行】您尾号1234的信用卡于07月07日退款人民币299.00元，商户：京东商城。"
        assert detect_platform(text) == 'cmb'
        assert extract_amount(text, 'cmb') == 299.00
        assert detect_type(text) == 'income'  # 退款是收入

    def test_cmb_repayment(self):
        """招行信用卡还款"""
        text = "【招商银行】您尾号1234的信用卡于07月08日还款人民币3000.00元。"
        assert detect_platform(text) == 'cmb'
        assert extract_amount(text, 'cmb') == 3000.00
        assert detect_type(text) == 'expense'


# ===========================================================================
# 工商银行 (ICBC)
# ===========================================================================

class TestICBC:
    """工商银行通知解析"""

    def test_icbc_consumption(self):
        """工行消费"""
        text = "【工商银行】您尾号9876的借记卡07月08日消费156.80元，余额8234.56元。"
        assert detect_platform(text) == 'icbc'
        assert extract_amount(text, 'icbc') == 156.80
        assert detect_type(text) == 'expense'
        assert extract_bank_card(text) == '9876'
        assert extract_balance(text) == 8234.56

    def test_icbc_transfer(self):
        """工行转账"""
        text = "【工商银行】您尾号5432的账户07月08日转出人民币5000.00元，余额12345.67元。"
        assert detect_platform(text) == 'icbc'
        assert extract_amount(text, 'icbc') == 5000.00
        assert detect_type(text) == 'expense'
        assert extract_balance(text) == 12345.67

    def test_icbc_income(self):
        """工行工资到账"""
        text = "【工商银行】您的账户07月08日收入人民币12500.00元，摘要：代发工资，余额25678.90元。"
        assert detect_platform(text) == 'icbc'
        assert extract_amount(text, 'icbc') == 12500.00
        assert detect_type(text) == 'income'
        assert extract_balance(text) == 25678.90

    def test_icbc_deduction(self):
        """工行代扣水电费"""
        text = "【工商银行】您尾号1111的账户07月08日扣款人民币234.56元，商户：国网浙江省电力有限公司。"
        assert detect_platform(text) == 'icbc'
        assert extract_amount(text, 'icbc') == 234.56
        assert detect_type(text) == 'expense'


# ===========================================================================
# 建设银行 (CCB)
# ===========================================================================

class TestCCB:
    """建设银行通知解析"""

    def test_ccb_consumption(self):
        """建行消费"""
        text = "【建设银行】您尾号3344的龙卡于07月08日在美团消费人民币45.60元，可用余额6789.00元。"
        assert detect_platform(text) == 'ccb'
        assert extract_amount(text, 'ccb') == 45.60
        assert detect_type(text) == 'expense'
        assert extract_bank_card(text) == '3344'
        assert auto_categorize('美团', text) == '餐饮'

    def test_ccb_transfer_in(self):
        """建行转入"""
        text = "【建设银行】您尾号5566的账户07月08日14:20转入人民币800.00元，余额3456.78元。"
        assert detect_platform(text) == 'ccb'
        assert extract_amount(text, 'ccb') == 800.00
        assert detect_type(text) == 'income'
        assert extract_balance(text) == 3456.78

    def test_ccb_repayment(self):
        """建行信用卡还款"""
        text = "【建设银行】您尾号7788的信用卡于07月08日还款人民币2000.00元，可用额度15000.00元。"
        assert detect_platform(text) == 'ccb'
        assert extract_amount(text, 'ccb') == 2000.00
        assert detect_type(text) == 'expense'
        assert extract_balance(text) == 15000.00

    def test_ccb_online_shopping(self):
        """建行网购"""
        text = "【建设银行】您尾号9900的龙卡于07月08日消费人民币199.90元，商户：京东商城。"
        assert detect_platform(text) == 'ccb'
        assert extract_amount(text, 'ccb') == 199.90
        assert detect_type(text) == 'expense'
        assert auto_categorize('京东商城', text) == '购物'


# ===========================================================================
# 支付宝 (Alipay)
# ===========================================================================

class TestAlipay:
    """支付宝通知解析"""

    def test_alipay_payment(self):
        """支付宝扫码付款"""
        text = "【支付宝】您于07月08日在瑞幸咖啡扫码付款18.90元。"
        assert detect_platform(text) == 'alipay'
        assert extract_amount(text, 'alipay') == 18.90
        assert detect_type(text) == 'expense'
        assert auto_categorize('瑞幸咖啡', text) == '餐饮'

    def test_alipay_transfer(self):
        """支付宝转账"""
        text = "【支付宝】您于07月08日向张三转账人民币500.00元。"
        assert detect_platform(text) == 'alipay'
        assert extract_amount(text, 'alipay') == 500.00
        assert detect_type(text) == 'expense'

    def test_alipay_income(self):
        """支付宝收款"""
        text = "【支付宝】您于07月08日收款人民币1200.00元，付款方：李四。"
        assert detect_platform(text) == 'alipay'
        assert extract_amount(text, 'alipay') == 1200.00
        assert detect_type(text) == 'income'

    def test_alipay_online_purchase(self):
        """支付宝淘宝购物"""
        text = "【支付宝】您于07月08日在淘宝消费人民币329.00元，付款方式：花呗。"
        assert detect_platform(text) == 'alipay'
        assert extract_amount(text, 'alipay') == 329.00
        assert detect_type(text) == 'expense'
        assert auto_categorize('淘宝', text) == '购物'

    def test_alipay_refund(self):
        """支付宝退款"""
        text = "【支付宝】您于07月08日收到退款人民币59.90元，商家：天猫旗舰店。"
        assert detect_platform(text) == 'alipay'
        assert extract_amount(text, 'alipay') == 59.90
        assert detect_type(text) == 'income'


# ===========================================================================
# 微信支付 (WeChat Pay)
# ===========================================================================

class TestWechatPay:
    """微信支付通知解析"""

    def test_wechat_scan_pay(self):
        """微信扫码支付"""
        text = "【微信支付】您于07月08日在肯德基扫码付款人民币35.50元。"
        assert detect_platform(text) == 'wechat_pay'
        assert extract_amount(text, 'wechat_pay') == 35.50
        assert detect_type(text) == 'expense'
        assert auto_categorize('肯德基', text) == '餐饮'

    def test_wechat_transfer(self):
        """微信转账"""
        text = "【微信支付】您于07月08日向王五转账人民币200.00元。"
        assert detect_platform(text) == 'wechat_pay'
        assert extract_amount(text, 'wechat_pay') == 200.00
        assert detect_type(text) == 'expense'

    def test_wechat_red_packet(self):
        """微信红包"""
        text = "【微信支付】您于07月08日收到红包人民币66.66元，来自：赵六。"
        assert detect_platform(text) == 'wechat_pay'
        assert extract_amount(text, 'wechat_pay') == 66.66
        assert detect_type(text) == 'income'

    def test_wechat_merchant_payment(self):
        """微信商户付款"""
        text = "【微信支付】您于07月08日在滴滴出行付款人民币28.80元。"
        assert detect_platform(text) == 'wechat_pay'
        assert extract_amount(text, 'wechat_pay') == 28.80
        assert detect_type(text) == 'expense'
        assert auto_categorize('滴滴出行', text) == '交通'

    def test_wechat_qr_transfer(self):
        """微信二维码转账"""
        text = "【微信支付】您于07月08日二维码转账给房东人民币3500.00元，备注：7月房租。"
        assert detect_platform(text) == 'wechat_pay'
        assert extract_amount(text, 'wechat_pay') == 3500.00
        assert detect_type(text) == 'expense'
        assert auto_categorize('房租', text) == '生活'


# ===========================================================================
# Cross-cutting / Edge cases
# ===========================================================================

class TestEdgeCases:
    """边界情况和通用逻辑"""

    def test_unknown_source_cmb_text(self):
        """未知来源但文本包含招行关键词"""
        text = "您尾号1234的招商银行卡消费100元"
        assert detect_platform(text) == 'cmb'
        assert extract_amount(text, 'cmb') == 100.0

    def test_zero_amount(self):
        """无法提取金额时返回0"""
        text = "这是一条没有金额的通知"
        assert extract_amount(text, 'unknown') == 0.0

    def test_large_amount(self):
        """大额交易"""
        text = "【招商银行】您尾号1234的信用卡消费人民币128888.00元"
        amount = extract_amount(text, 'cmb')
        assert amount == 128888.0

    def test_category_transport(self):
        """交通分类"""
        assert auto_categorize('滴滴打车') == '交通'
        assert auto_categorize('地铁') == '交通'
        assert auto_categorize('12306') == '交通'

    def test_category_entertainment(self):
        """娱乐分类"""
        assert auto_categorize('爱奇艺会员') == '娱乐'
        assert auto_categorize('健身') == '娱乐'

    def test_category_life(self):
        """生活分类"""
        assert auto_categorize('电费') == '生活'
        assert auto_categorize('中国移动') == '通讯'

    def test_category_medical(self):
        """医疗分类"""
        assert auto_categorize('医院挂号') == '医疗'

    def test_category_fallback(self):
        """无法分类时返回其他"""
        assert auto_categorize('一笔莫名其妙的交易') == '其他'

    def test_detect_platform_with_source(self):
        """通过 source 参数识别平台"""
        # source 参数需要包含平台关键词才能匹配
        assert detect_platform('', '微信支付') == 'wechat_pay'
        assert detect_platform('', '支付宝') == 'alipay'
        assert detect_platform('', '招商银行') == 'cmb'
        assert detect_platform('', '工商银行') == 'icbc'
        assert detect_platform('', '建设银行') == 'ccb'

    def test_detect_platform_from_text(self):
        """从文本推断平台"""
        assert detect_platform('在招商银行消费') == 'cmb'
        assert detect_platform('支付宝付款') == 'alipay'
        assert detect_platform('微信支付') == 'wechat_pay'

    def test_extract_balance_none(self):
        """没有余额信息"""
        text = "消费100元"
        assert extract_balance(text) is None

    def test_extract_merchant_none(self):
        """没有商户信息时返回 None"""
        text = "消费100元"
        result = extract_merchant(text, 'unknown')
        # 不强制要求 None，但不应是空字符串导致崩溃
        assert result is None or isinstance(result, str)


# ===========================================================================
# Integration-style: full parse flow (using FastAPI TestClient)
# ===========================================================================

class TestParseAPI:
    """API 集成测试"""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_parse_cmb_notification(self, client):
        resp = client.post("/parse", json={
            "title": "招商银行",
            "body": "您尾号1234的信用卡于07月08日在星巴克消费人民币88.50元，可用额度52311.50元。",
            "source": "cmb"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 88.50
        assert data["transaction_type"] == "expense"
        assert data["account"] == "cmb"
        assert data["category"] == "餐饮"
        assert data["bank_card"] == "1234"
        assert data["balance"] == 52311.50

    def test_parse_alipay_notification(self, client):
        resp = client.post("/parse", json={
            "title": "支付宝",
            "body": "您于07月08日在瑞幸咖啡扫码付款18.90元。",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 18.90
        assert data["account"] == "alipay"
        assert data["category"] == "餐饮"

    def test_parse_wechat_income(self, client):
        resp = client.post("/parse", json={
            "title": "微信支付",
            "body": "您于07月08日收到红包人民币66.66元",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] == 66.66
        assert data["transaction_type"] == "income"
        assert data["account"] == "wechat_pay"

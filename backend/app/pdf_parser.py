"""
银行 PDF 流水解析器
当前支持：招商银行标准格式
"""

import re
from datetime import datetime
from typing import List, Dict, Optional
import pdfplumber
import io


# 招商银行交易记录正则
# 格式：日期 摘要 借方 贷方 余额 账户
CMB_PATTERNS = [
    # 消费/支出：2024/01/15 美团-美团App 31.90 6025.93
    re.compile(r'(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\s+(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'),
    # 带借贷方向的：2024/01/15 消费-美团 支出 31.90 6025.93
    re.compile(r'(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\s+(.+?)\s+(支出|收入|借|贷)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'),
]

# 分类关键词映射
CATEGORY_MAP = {
    '美团': '餐饮', '饿了么': '餐饮', '大众点评': '餐饮',
    '肯德基': '餐饮', '麦当劳': '餐饮', '星巴克': '餐饮', '瑞幸': '餐饮',
    '滴滴': '交通', '高德': '交通', '地铁': '交通', '公交': '交通',
    '淘宝': '购物', '京东': '购物', '拼多多': '购物', '天猫': '购物',
    '微信': '社交', '支付宝': '转账',
    '房租': '房租', '物业': '房租',
    '话费': '话费', '移动': '话费', '联通': '话费', '电信': '话费',
    '水电': '水电', '燃气': '水电', '电力': '水电',
    '医院': '医疗', '药房': '医疗',
    '电影': '娱乐', '游戏': '娱乐', '网易': '娱乐',
    '工资': '工资', '薪资': '工资', '奖金': '工资',
    '转账': '转账',
}


def guess_category(description: str) -> str:
    """根据描述猜测分类"""
    for keyword, category in CATEGORY_MAP.items():
        if keyword in description:
            return category
    return '其他'


def parse_cmb_pdf(pdf_content: bytes) -> List[Dict]:
    """
    解析招商银行 PDF 流水
    
    返回格式：
    [
        {
            "date": "2024-01-15",
            "description": "美团-美团App",
            "amount": 31.90,
            "balance": 6025.93,
            "transaction_type": "expense",  # income/expense
            "category": "餐饮",
            "account": "招商银行",
            "confidence": 0.8
        }
    ]
    """
    results = []
    
    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            
            # 尝试提取表格
            tables = page.extract_tables()
            if tables:
                for table in tables:
                    for row in table:
                        if not row or len(row) < 3:
                            continue
                        parsed = _parse_cmb_table_row(row)
                        if parsed:
                            results.append(parsed)
            
            # 如果表格提取失败，尝试正则匹配文本
            if not results:
                lines = text.split('\n')
                for line in lines:
                    parsed = _parse_cmb_text_line(line)
                    if parsed:
                        results.append(parsed)
    
    return results


def _parse_cmb_table_row(row: List) -> Optional[Dict]:
    """解析表格行"""
    try:
        # 常见列顺序：日期 | 摘要 | 借方(支出) | 贷方(收入) | 余额
        date_str = str(row[0]).strip() if row[0] else ''
        if not re.match(r'\d{4}[/\-]\d{1,2}[/\-]\d{1,2}', date_str):
            return None
        
        # 标准化日期
        date_str = date_str.replace('/', '-')
        parts = date_str.split('-')
        if len(parts) == 3:
            date_str = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        
        description = str(row[1]).strip() if len(row) > 1 and row[1] else ''
        
        # 判断借贷方向
        debit = _parse_amount(row[2]) if len(row) > 2 else 0  # 借方=支出
        credit = _parse_amount(row[3]) if len(row) > 3 else 0  # 贷方=收入
        balance = _parse_amount(row[4]) if len(row) > 4 else 0
        
        if debit > 0:
            amount = debit
            tx_type = 'expense'
        elif credit > 0:
            amount = credit
            tx_type = 'income'
        else:
            return None
        
        return {
            'date': date_str,
            'description': description,
            'amount': amount,
            'balance': balance,
            'transaction_type': tx_type,
            'category': guess_category(description),
            'account': '招商银行',
            'confidence': 0.85
        }
    except Exception:
        return None


def _parse_cmb_text_line(line: str) -> Optional[Dict]:
    """从文本行解析交易"""
    # 模式1：日期 摘要 金额 余额
    m = re.match(r'(\d{4}[/\-]\d{1,2}[/\-]\d{1,2})\s+(.+?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})', line)
    if m:
        date_str = m.group(1).replace('/', '-')
        parts = date_str.split('-')
        if len(parts) == 3:
            date_str = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        
        description = m.group(2).strip()
        amount = _parse_amount(m.group(3))
        balance = _parse_amount(m.group(4))
        
        # 默认当支出处理（如果有贷方标记则改）
        tx_type = 'expense'
        if '收入' in line or '贷' in line:
            tx_type = 'income'
        
        return {
            'date': date_str,
            'description': description,
            'amount': amount,
            'balance': balance,
            'transaction_type': tx_type,
            'category': guess_category(description),
            'account': '招商银行',
            'confidence': 0.7
        }
    return None


def _parse_amount(val) -> float:
    """解析金额字符串"""
    if val is None:
        return 0.0
    val_str = str(val).strip().replace(',', '').replace(' ', '')
    if not val_str or val_str in ('-', '--', ''):
        return 0.0
    try:
        return float(val_str)
    except ValueError:
        return 0.0


def detect_bank(pdf_content: bytes) -> str:
    """检测 PDF 来源银行"""
    try:
        with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
            first_page_text = pdf.pages[0].extract_text() or ''
            if '招商银行' in first_page_text:
                return 'cmb'
            elif '工商银行' in first_page_text or 'ICBC' in first_page_text:
                return 'icbc'
            elif '建设银行' in first_page_text or 'CCB' in first_page_text:
                return 'ccb'
            elif '支付宝' in first_page_text:
                return 'alipay'
            elif '微信' in first_page_text:
                return 'wechat'
    except Exception:
        pass
    return 'unknown'


def parse_pdf(pdf_content: bytes) -> Dict:
    """
    通用 PDF 解析入口
    
    返回：
    {
        "bank": "cmb",
        "transactions": [...],
        "total": 10,
        "parsed": 8,
        "skipped": 2
    }
    """
    bank = detect_bank(pdf_content)
    
    if bank == 'cmb':
        transactions = parse_cmb_pdf(pdf_content)
    else:
        # 尝试通用解析（按招行格式）
        transactions = parse_cmb_pdf(pdf_content)
        if transactions:
            bank = 'unknown (parsed as cmb format)'
    
    return {
        'bank': bank,
        'transactions': transactions,
        'total': len(transactions),
        'parsed': len([t for t in transactions if t.get('amount', 0) > 0]),
        'skipped': len([t for t in transactions if t.get('amount', 0) == 0])
    }

"""
SilentBook 资产同步服务
- 基金净值：天天基金 API
- 股票价格：新浪财经 API
- 黄金价格：上海黄金交易所 / 备用 API
- 银行理财：手动更新（无公开 API）

每日 15:30（北京时间）自动同步，也可手动触发。
"""
import httpx
import re
import json
import logging
from datetime import datetime, date
from typing import Optional, Dict, List, Tuple
from sqlalchemy.orm import Session

logger = logging.getLogger("silentbook.asset_sync")

# ===== 数据源配置 =====
FUND_API_URL = "https://fundgz.1234567.com.cn/js/{code}.js"
STOCK_API_URL = "https://hq.sinajs.cn/list={codes}"
GOLD_API_URL = "https://api.jijinhao.com/quoteCenter/realTime.htm?codes=JO_52683"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://fund.eastmoney.com/",
}


# ===== 基金净值 =====
async def fetch_fund_nav(code: str) -> Optional[Dict]:
    """
    获取基金实时估值/净值
    返回: {"nav": 净值, "nav_date": 日期, "estimated": 估值, "change_pct": 涨跌幅}
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                FUND_API_URL.format(code=code),
                headers=HEADERS,
            )
            text = resp.text
            # 解析 JSONP: jsonpgz({"fundcode":"110011","name":"...","jzrq":"2026-07-10","dwjz":"1.2345","gsz":"1.2400","gszzl":"0.45",...});
            match = re.search(r'jsonpgz\((.*)\)', text)
            if not match:
                logger.warning(f"基金 {code} API 返回格式异常")
                return None
            
            data = json.loads(match.group(1))
            return {
                "nav": float(data.get("dwjz", 0)),  # 单位净值
                "nav_date": data.get("jzrq", ""),  # 净值日期
                "estimated": float(data.get("gsz", 0)),  # 实时估值
                "change_pct": float(data.get("gszzl", 0)),  # 估算涨跌幅
                "name": data.get("name", ""),
            }
    except Exception as e:
        logger.error(f"获取基金 {code} 净值失败: {e}")
        return None


# ===== 股票价格 =====
async def fetch_stock_price(code: str) -> Optional[Dict]:
    """
    获取 A 股实时价格
    code: 6位代码，如 600519, 000858
    返回: {"price": 当前价, "change_pct": 涨跌幅, "name": 名称, "date": 日期}
    """
    try:
        # 判断市场：6开头=上海(sh)，0/3开头=深圳(sz)
        prefix = "sh" if code.startswith("6") else "sz"
        sina_code = f"{prefix}{code}"
        
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                STOCK_API_URL.format(codes=sina_code),
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://finance.sina.com.cn/",
                },
            )
            text = resp.text
            # 解析: var hq_str_sh600519="贵州茅台,1800.00,..."
            match = re.search(r'"(.+)"', text)
            if not match:
                logger.warning(f"股票 {code} API 返回为空")
                return None
            
            fields = match.group(1).split(",")
            if len(fields) < 32:
                return None
            
            return {
                "name": fields[0],
                "open": float(fields[1]) if fields[1] else 0,
                "prev_close": float(fields[2]) if fields[2] else 0,
                "price": float(fields[3]) if fields[3] else 0,
                "high": float(fields[4]) if fields[4] else 0,
                "low": float(fields[5]) if fields[5] else 0,
                "volume": float(fields[8]) if fields[8] else 0,
                "amount": float(fields[9]) if fields[9] else 0,
                "date": fields[30],
                "change_pct": round(
                    (float(fields[3]) - float(fields[2])) / float(fields[2]) * 100, 2
                ) if fields[2] and float(fields[2]) > 0 else 0,
            }
    except Exception as e:
        logger.error(f"获取股票 {code} 价格失败: {e}")
        return None


# ===== 黄金价格 =====
async def fetch_gold_price() -> Optional[Dict]:
    """
    获取黄金实时价格（Au99.99）
    返回: {"price": 元/克, "change_pct": 涨跌幅}
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(GOLD_API_URL, headers=HEADERS)
            data = resp.json()
            
            if "result" in data and len(data["result"]) > 0:
                item = data["result"][0]
                return {
                    "price": float(item.get("currentPrice", 0)),
                    "change_pct": float(item.get("riseAndFall", 0)),
                    "name": "Au99.99",
                    "unit": "元/克",
                }
    except Exception as e:
        logger.error(f"获取黄金价格失败: {e}")
    
    # 备用：尝试另一个 API
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.gold-api.com/price/XAU",
                timeout=10,
            )
            data = resp.json()
            if "price" in data:
                # 国际金价 USD/oz → 人民币/克（近似换算）
                usd_price = data["price"]
                # 1 oz = 31.1035 g, 假设汇率 7.25
                cny_per_gram = round(usd_price / 31.1035 * 7.25, 2)
                return {
                    "price": cny_per_gram,
                    "change_pct": 0,
                    "name": "XAU(国际)",
                    "unit": "元/克(估算)",
                }
    except Exception as e:
        logger.error(f"备用黄金 API 也失败: {e}")
    
    return None


# ===== 批量同步 =====
async def sync_all_positions(db: Session) -> Dict:
    """
    同步所有活跃持仓的实时价格
    返回: {"updated": N, "failed": N, "details": [...]}
    """
    from .database import Position
    
    positions = db.query(Position).filter(Position.status == "active").all()
    if not positions:
        return {"updated": 0, "failed": 0, "details": [], "message": "无活跃持仓"}
    
    results = []
    updated = 0
    failed = 0
    
    # 按类型分组，减少 API 调用
    stocks = [p for p in positions if p.position_type == "stock" and p.symbol]
    funds = [p for p in positions if p.position_type == "fund" and p.symbol]
    gold_positions = [p for p in positions if "黄金" in p.name or "gold" in p.name.lower()]
    others = [p for p in positions if p not in stocks + funds + gold_positions]
    
    # 1. 同步股票（批量查询）
    if stocks:
        stock_codes = [p.symbol for p in stocks]
        # 新浪 API 支持批量，用逗号分隔
        prefix_codes = []
        for code in stock_codes:
            prefix = "sh" if code.startswith("6") else "sz"
            prefix_codes.append(f"{prefix}{code}")
        
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    STOCK_API_URL.format(codes=",".join(prefix_codes)),
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.sina.com.cn/",
                    },
                )
                text = resp.text
            
            # 解析多股票返回
            lines = text.strip().split("\n")
            price_map = {}
            for line in lines:
                match_code = re.search(r'hq_str_(s[hz]\d{6})="(.+)"', line)
                if match_code:
                    sina_code = match_code.group(1)
                    fields = match_code.group(2).split(",")
                    code = sina_code[2:]  # 去掉 sh/sz 前缀
                    if len(fields) >= 32 and fields[3]:
                        price_map[code] = {
                            "price": float(fields[3]),
                            "name": fields[0],
                            "change_pct": round(
                                (float(fields[3]) - float(fields[2])) / float(fields[2]) * 100, 2
                            ) if fields[2] and float(fields[2]) > 0 else 0,
                        }
        except Exception as e:
            logger.error(f"批量获取股票价格失败: {e}")
            price_map = {}
        
        for pos in stocks:
            if pos.symbol in price_map:
                info = price_map[pos.symbol]
                old_price = pos.current_price
                pos.current_price = info["price"]
                pos.updated_at = datetime.utcnow()
                updated += 1
                pnl = (info["price"] - pos.avg_cost) * pos.quantity if pos.avg_cost else 0
                results.append({
                    "name": pos.name,
                    "symbol": pos.symbol,
                    "type": "stock",
                    "old_price": old_price,
                    "new_price": info["price"],
                    "change_pct": info["change_pct"],
                    "pnl": round(pnl, 2),
                })
            else:
                failed += 1
                results.append({
                    "name": pos.name,
                    "symbol": pos.symbol,
                    "type": "stock",
                    "error": "获取价格失败",
                })
    
    # 2. 同步基金（逐个查询）
    for pos in funds:
        nav_data = await fetch_fund_nav(pos.symbol)
        if nav_data and nav_data["nav"] > 0:
            old_price = pos.current_price
            pos.current_price = nav_data["nav"]
            pos.updated_at = datetime.utcnow()
            updated += 1
            pnl = (nav_data["nav"] - pos.avg_cost) * pos.quantity if pos.avg_cost else 0
            results.append({
                "name": pos.name or nav_data.get("name", pos.name),
                "symbol": pos.symbol,
                "type": "fund",
                "old_price": old_price,
                "new_price": nav_data["nav"],
                "change_pct": nav_data.get("change_pct", 0),
                "nav_date": nav_data.get("nav_date", ""),
                "pnl": round(pnl, 2),
            })
        else:
            failed += 1
            results.append({
                "name": pos.name,
                "symbol": pos.symbol,
                "type": "fund",
                "error": "获取净值失败",
            })
    
    # 3. 同步黄金
    if gold_positions:
        gold_data = await fetch_gold_price()
        if gold_data:
            for pos in gold_positions:
                old_price = pos.current_price
                pos.current_price = gold_data["price"]
                pos.updated_at = datetime.utcnow()
                updated += 1
                results.append({
                    "name": pos.name,
                    "type": "gold",
                    "old_price": old_price,
                    "new_price": gold_data["price"],
                    "change_pct": gold_data.get("change_pct", 0),
                    "unit": gold_data.get("unit", "元/克"),
                })
        else:
            for pos in gold_positions:
                failed += 1
                results.append({
                    "name": pos.name,
                    "type": "gold",
                    "error": "获取金价失败",
                })
    
    # 4. 其他类型（银行理财等）不自动同步
    for pos in others:
        results.append({
            "name": pos.name,
            "type": pos.position_type,
            "status": "跳过（无自动数据源）",
        })
    
    db.commit()
    
    # 同步更新资产表中的持仓对应条目
    from .database import Asset
    assets_updated = 0
    for pos in positions:
        if pos.status != "active":
            continue
        market_value = pos.quantity * pos.current_price
        # 通过持仓ID精确匹配资产
        linked_asset = db.query(Asset).filter(
            Asset.notes == f"关联持仓ID={pos.id}, 代码={pos.symbol or 'N/A'}",
            Asset.status == "active"
        ).first()
        if not linked_asset:
            # fallback: 按名称匹配
            linked_asset = db.query(Asset).filter(
                Asset.name == f"[持仓] {pos.name}",
                Asset.status == "active"
            ).first()
        if linked_asset:
            old_value = linked_asset.current_value
            linked_asset.current_value = market_value
            linked_asset.updated_at = datetime.utcnow()
            if abs(old_value - market_value) > 0.01:
                assets_updated += 1
    
    if assets_updated > 0:
        db.commit()
        logger.info(f"资产表同步更新: {assets_updated} 条")
    
    return {
        "updated": updated,
        "failed": failed,
        "skipped": len(others),
        "total": len(positions),
        "assets_synced": assets_updated,
        "details": results,
        "synced_at": datetime.utcnow().isoformat(),
    }

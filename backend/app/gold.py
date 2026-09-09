"""黄金现货参考价抓取（assets 金价接口 + asset_sync 定时同步共用）。

2026-09 实测：上海金交所 au0 直连返回空、集金号/烁石接口已死；
COMEX 黄金期货 hf_GC（新浪，带 Referer）在国内外均可达。
口径诚实标注为“COMEX黄金(换算)”，个人记账跟踪够用。
"""
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_SINA_HEADERS = {"Referer": "https://finance.sina.com.cn"}
_GRAMS_PER_OZ = 31.1035


async def _usd_cny() -> float:
    """美元兑人民币，取新浪外汇中间价，失败回退 7.2。"""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://hq.sinajs.cn/list=fx_susdcny", headers=_SINA_HEADERS
            )
            fields = resp.text.strip().split("=", 1)[1].strip().strip('";').split(",")
            v = float(fields[3])
            if 5.0 < v < 10.0:
                return v
    except Exception as e:
        logger.warning(f"USD/CNY 获取失败，用 7.2 兜底: {e}")
    return 7.2


async def fetch_gold_quote() -> Optional[dict]:
    """返回 {"price": 元/克, "source": 来源}，全失败返回 None（不抛）。"""
    # 主源：COMEX 黄金期货 USD/oz → 元/克
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://hq.sinajs.cn/list=hf_GC", headers=_SINA_HEADERS
            )
            fields = resp.text.strip().split("=", 1)[1].strip().strip('";').split(",")
            usd_per_oz = float(fields[0])
            if usd_per_oz > 0:
                rate = await _usd_cny()
                return {
                    "price": round(usd_per_oz / _GRAMS_PER_OZ * rate, 2),
                    "source": "COMEX黄金(换算)",
                }
    except Exception as e:
        logger.warning(f"COMEX 金价失败: {e}")
    # 备用：gold-api 现货（国内常不可达，留给海外部署）
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("https://api.gold-api.com/price/XAU")
            data = resp.json()
            if "price" in data:
                rate = await _usd_cny()
                return {
                    "price": round(float(data["price"]) / _GRAMS_PER_OZ * rate, 2),
                    "source": "国际金价(换算)",
                }
    except Exception as e:
        logger.warning(f"备用金价失败: {e}")
    return None

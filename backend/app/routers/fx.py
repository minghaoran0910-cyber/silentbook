import logging
import os
import time
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Optional
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks, UploadFile, File, Header
from pydantic import BaseModel, Field
from sqlalchemy import func, case, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal, Transaction, AnalysisResult, Asset, Liability, AgentConfig, Setting, User, Account, Transfer, BackupRecord, FinancialGoal, GoalContribution, RecurringTransaction, init_db, SyncLog, WebhookEvent, Position, TradeRecord
from ..schemas import (
    TransactionCreate, TransactionUpdate, TransactionResponse,
    AnalysisResponse, DashboardStats,
    AssetCreate, AssetUpdate, AssetResponse,
    LiabilityCreate, LiabilityUpdate, LiabilityResponse,
    AccountCreate, AccountUpdate, AccountResponse, AccountTransfer, TransferResponse,
    GoalCreate, GoalUpdate, GoalResponse, GoalContributionCreate, GoalContributionResponse, GoalSummaryResponse,
    RecurringTransactionCreate, RecurringTransactionUpdate, RecurringTransactionResponse,
    RecurringSummaryResponse, AutoDetectResponse
)
from ..auth import require_user
from ..tenant import set_tenant_user_id, reset_tenant_user_id
from ..notification_push import pusher
from ..backup_crypto import read_backup, write_backup
from ..logging_config import setup_logging, log_buffer, generate_request_id, set_request_context
from .deps import (
    AGENT_API_URL, PARSER_API_URL, OPENCLAW_GATEWAY_URL,
    PLATFORM_ACCOUNT_MAP, LOW_BALANCE_THRESHOLD,
    ALERT_LEVELS, DEFAULT_ALERT_THRESHOLDS,
    LEVEL_LABELS, LEVEL_COMPRESSIBILITY, DEFAULT_CATEGORY_LEVELS,
    _update_account_balance, _check_low_balance_alert,
    _webhook_item_hash, _is_duplicate_body, _is_placeholder_analysis,
    get_alert_level, get_category_level,
)

router = APIRouter()

logger = logging.getLogger("silentbook")


# ===== 外汇汇率（展示层折算专用，不动账本）=====
# 主源 Frankfurter（免费免 Key）：https://api.frankfurter.dev/v2/rates
# 备源 新浪财经 hq.sinajs.cn（与金价/股价同通道，国内快）：fx_s<ccy>cny 中间价
# 缓存 6 小时；双源都挂时返回最后一次可用快照并标记 stale。

SUPPORTED_QUOTES = ["USD", "EUR", "JPY", "HKD", "GBP", "AUD", "CAD", "CHF", "SGD"]
SINA_FX_SYMBOLS = {
    "USD": "fx_susdcny", "EUR": "fx_seurcny", "GBP": "fx_sgbpcny",
    "JPY": "fx_sjpycny", "HKD": "fx_shkdcny", "AUD": "fx_saudcny",
    "CAD": "fx_scadccny", "CHF": "fx_schfcny", "SGD": "fx_ssgdcny",
}
FX_TTL_SECONDS = int(os.getenv("FX_CACHE_TTL", "21600"))
_fx_cache: dict = {"at": 0.0, "date": "", "rates": {}, "source": ""}


def _parse_frankfurter(payload: dict, quotes: List[str]) -> dict:
    """容忍 v1/v2 两种形状：{rates:{USD:x}} 或 [{base,quote,rate}]."""
    rates = {}
    if isinstance(payload, dict):
        raw = payload.get("rates", payload)
        if isinstance(raw, dict):
            for q in quotes:
                v = raw.get(q)
                if isinstance(v, (int, float)) and v > 0:
                    rates[q] = float(v)
    elif isinstance(payload, list):
        for row in payload:
            if not isinstance(row, dict):
                continue
            q = row.get("quote")
            v = row.get("rate")
            if q in quotes and isinstance(v, (int, float)) and v > 0:
                rates[q] = float(v)
    return rates


async def _fetch_frankfurter(base: str, quotes: List[str]) -> tuple:
    url = "https://api.frankfurter.dev/v2/rates"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, params={"base": base, "quotes": ",".join(quotes)})
        resp.raise_for_status()
        payload = resp.json()
    rates = _parse_frankfurter(payload, quotes)
    if not rates:
        raise ValueError("frankfurter empty rates")
    date = ""
    if isinstance(payload, dict):
        date = str(payload.get("date", ""))
    return rates, date or time.strftime("%Y-%m-%d")


def _parse_sina_line(line: str) -> Optional[float]:
    """var hq_str_fx_susdcny="美元人民币,买,卖,中间,..."; 取中间价。"""
    try:
        data = line.split("=", 1)[1].strip().strip('";')
        fields = data.split(",")
        v = float(fields[3])
        return v if v > 0 else None
    except (IndexError, ValueError):
        return None


async def _fetch_sina(quotes: List[str]) -> tuple:
    """备源只支持 base=CNY（新浪给的是外币兑人民币中间价，取倒数即 CNY->外币）。"""
    symbols = [SINA_FX_SYMBOLS[q] for q in quotes if q in SINA_FX_SYMBOLS]
    if not symbols:
        raise ValueError("sina unsupported quotes")
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            "https://hq.sinajs.cn/list=" + ",".join(symbols),
            headers={"Referer": "https://finance.sina.com.cn",
                     "User-Agent": "Mozilla/5.0 SilentBookFX/1.0"},
        )
        resp.raise_for_status()
        lines = resp.text.splitlines()
    rates = {}
    for q, line in zip([x for x in quotes if x in SINA_FX_SYMBOLS], lines):
        v = _parse_sina_line(line)
        if v:
            rates[q] = round(1.0 / v, 6)
    if not rates:
        raise ValueError("sina empty rates")
    return rates, time.strftime("%Y-%m-%d")


@router.get("/fx/rates")
async def get_fx_rates(
    base: str = Query(default="CNY", min_length=3, max_length=3),
    quotes: str = Query(default="USD,EUR,JPY,HKD,GBP"),
    user: User = Depends(require_user),
):
    """展示层汇率：base 计价，返回各 quote 的 1 base = x quote。

    frankfurter 主源 + 新浪备源 + 6h 缓存；双挂时回最后快照（stale=true）。
    """
    base = base.upper()
    want = [q.strip().upper() for q in quotes.split(",") if q.strip().upper()]
    want = [q for q in want if q in SUPPORTED_QUOTES][:10]
    if not want:
        raise HTTPException(status_code=400, detail="不支持的币种")
    if base in want:
        want.remove(base)

    now = time.time()
    if _fx_cache["rates"] and now - _fx_cache["at"] < FX_TTL_SECONDS and base == "CNY":
        return {"base": base, "date": _fx_cache["date"], "rates": {
            k: v for k, v in _fx_cache["rates"].items() if k in want
        }, "source": _fx_cache["source"], "stale": False}

    errors = []
    if base == "CNY":
        try:
            rates, date = await _fetch_frankfurter(base, want)
            _fx_cache.update({"at": now, "date": date, "rates": rates,
                              "source": "frankfurter"})
            return {"base": base, "date": date, "rates": rates,
                    "source": "frankfurter", "stale": False}
        except Exception as e:
            errors.append(f"frankfurter: {str(e)[:100]}")
        try:
            rates, date = await _fetch_sina(want)
            _fx_cache.update({"at": now, "date": date, "rates": rates,
                              "source": "sina"})
            return {"base": base, "date": date, "rates": rates,
                    "source": "sina", "stale": False}
        except Exception as e:
            errors.append(f"sina: {str(e)[:100]}")

    if _fx_cache["rates"]:
        return {"base": base, "date": _fx_cache["date"], "rates": {
            k: v for k, v in _fx_cache["rates"].items() if k in want
        }, "source": _fx_cache["source"], "stale": True}
    raise HTTPException(status_code=503, detail="汇率源不可用: " + "; ".join(errors))


@router.get("/fx/currencies")
async def list_fx_currencies(user: User = Depends(require_user)):
    """前端币种下拉用。"""
    return {"base": "CNY", "supported": SUPPORTED_QUOTES,
            "symbols": {"CNY": "¥", "USD": "$", "EUR": "€", "JPY": "¥",
                        "HKD": "HK$", "GBP": "£", "AUD": "A$", "CAD": "C$",
                        "CHF": "CHF ", "SGD": "S$"}}


@router.post("/fx/refresh")
async def refresh_fx_rates(user: User = Depends(require_user)):
    """强制刷新缓存（管理/调试用）。"""
    _fx_cache["at"] = 0.0
    return await get_fx_rates(base="CNY",
                              quotes=",".join(SUPPORTED_QUOTES),
                              user=user)

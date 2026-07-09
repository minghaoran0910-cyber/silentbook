"""
SilentBook Agent Engine v0.2

三种分析模式：
1. local — 本地 LLM（dashscope 直调，无需 OpenClaw）
2. openclaw — 对接 OpenClaw subagent（墨砚管消费、远瞻管投资）
3. auto — 优先 openclaw，fallback 到 local

环境变量：
- SILENTBOOK_MODE: local | openclaw | auto (默认 auto)
- OPENCLAW_GATEWAY_URL: OpenClaw Gateway 地址
- DASHSCOPE_API_KEY: 本地模式用的 API Key
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import httpx
import os
from datetime import datetime
import json
import asyncio

app = FastAPI(title="SilentBook Agent Engine", version="0.2.0")

# ===== 配置 =====
AGENT_MODE = os.getenv("SILENTBOOK_MODE", "auto")
OPENCLAW_GATEWAY_URL = os.getenv("OPENCLAW_GATEWAY_URL", "http://localhost:18789")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
MODEL_NAME = os.getenv("MODEL_NAME", "aliyun/glm-5.2")

# OpenClaw agent ID 映射
AGENT_MAP = {
    "consumption": "financial_director",  # 墨砚
    "investment": "investment_director",   # 远瞻
}

# ===== 数据模型 =====
class AnalysisRequest(BaseModel):
    transactions: List[Dict]
    assets: Optional[List[Dict]] = None
    liabilities: Optional[List[Dict]] = None
    prompt: Optional[str] = None
    agent_config: Optional[dict] = None

class AnalysisResponse(BaseModel):
    consumption: str
    investment: str
    suggestion: str
    mode: str = "local"  # local | openclaw

@app.get("/")
async def root():
    return {
        "message": "SilentBook Agent Engine",
        "version": "0.2.0",
        "mode": AGENT_MODE,
        "openclaw_gateway": OPENCLAW_GATEWAY_URL,
    }

@app.get("/health")
async def health():
    return {"status": "ok", "mode": AGENT_MODE}

# ===== 本地 LLM 调用（fallback） =====
async def call_llm(prompt: str, system_prompt: str = "") -> str:
    if not DASHSCOPE_API_KEY:
        return "⚠️ 未配置 DASHSCOPE_API_KEY，无法进行分析。"
    
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    # 使用 OpenAI 兼容接口
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{DASHSCOPE_BASE_URL}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            return result.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            return f"本地 LLM 调用失败: {str(e)}"

# ===== OpenClaw subagent 调用 =====
async def call_openclaw_agent(agent_id: str, task: str, timeout: int = 60) -> str:
    """
    通过 OpenClaw Gateway 的 sessions_spawn API 调用 subagent
    
    流程：
    1. POST /api/sessions/spawn 创建子会话
    2. 轮询结果
    3. 返回分析内容
    """
    headers = {"Content-Type": "application/json"}
    
    spawn_payload = {
        "agentId": agent_id,
        "task": task,
        "mode": "run",
        "runtime": "subagent",
    }
    
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            # 1. Spawn subagent
            resp = await client.post(
                f"{OPENCLAW_GATEWAY_URL}/api/sessions/spawn",
                headers=headers,
                json=spawn_payload
            )
            resp.raise_for_status()
            spawn_data = resp.json()
            session_key = spawn_data.get("sessionKey") or spawn_data.get("session_key")
            
            if not session_key:
                return f"OpenClaw spawn 成功但未返回 sessionKey"
            
            # 2. 等待结果（轮询，最多 timeout 秒）
            elapsed = 0
            interval = 3
            while elapsed < timeout:
                await asyncio.sleep(interval)
                elapsed += interval
                
                status_resp = await client.get(
                    f"{OPENCLAW_GATEWAY_URL}/api/sessions/{session_key}/status"
                )
                status_data = status_resp.json()
                status = status_data.get("status", "running")
                
                if status == "completed":
                    # 获取最后一条 assistant 消息
                    history_resp = await client.get(
                        f"{OPENCLAW_GATEWAY_URL}/api/sessions/{session_key}/history?limit=5"
                    )
                    history_data = history_resp.json()
                    messages = history_data.get("messages", [])
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant":
                            return msg.get("content", "（无内容）")
                    return "（Agent 未返回内容）"
                
                if status == "error" or status == "failed":
                    return f"Agent 执行失败: {status_data.get('error', '未知错误')}"
            
            return f"Agent 执行超时（{timeout}秒）"
            
        except httpx.ConnectError:
            return "⚠️ 无法连接 OpenClaw Gateway，请确认 Gateway 正在运行。"
        except Exception as e:
            return f"OpenClaw agent 调用失败: {str(e)}"

# ===== 数据格式化 =====
def format_transactions(transactions: List[Dict], limit: int = 50) -> str:
    """格式化交易数据为文本摘要"""
    lines = []
    for tx in transactions[:limit]:
        lines.append(
            f"  {tx.get('parsed_at', '')[:10]} | {tx.get('category', '')} | "
            f"{tx.get('transaction_type', '')} | ¥{tx.get('amount', 0)} | "
            f"{tx.get('description', '')}"
        )
    return "\n".join(lines) if lines else "  （无交易记录）"

def format_assets(assets: Optional[List[Dict]]) -> str:
    if not assets:
        return "  （无资产数据）"
    lines = []
    for a in assets:
        lines.append(
            f"  {a.get('name', '')} | {a.get('asset_type', '')} | "
            f"当前¥{a.get('current_value', 0)} | 初始¥{a.get('initial_value', 0)}"
        )
    return "\n".join(lines)

def format_liabilities(liabilities: Optional[List[Dict]]) -> str:
    if not liabilities:
        return "  （无负债数据）"
    lines = []
    for l in liabilities:
        lines.append(
            f"  {l.get('name', '')} | {l.get('liability_type', '')} | "
            f"待还¥{l.get('current_amount', 0)}/{l.get('total_amount', 0)}"
        )
    return "\n".join(lines)

# ===== 分析入口 =====
async def do_analysis(request: AnalysisRequest) -> AnalysisResponse:
    """
    根据模式选择分析路径：
    - local: 纯本地 LLM
    - openclaw: 纯 OpenClaw subagent
    - auto: 优先 openclaw，失败 fallback 到 local
    """
    tx_text = format_transactions(request.transactions)
    assets_text = format_assets(request.assets)
    liab_text = format_liabilities(request.liabilities)
    
    use_openclaw = AGENT_MODE in ("openclaw", "auto")
    mode_used = "local"
    
    consumption = ""
    investment = ""
    suggestion = ""
    
    if use_openclaw:
        mode_used = "openclaw"
        
        # 消费分析 — 墨砚
        consumption_task = f"""你是 SilentBook 的消费分析 Agent。请分析以下财务数据，给出消费分析。

交易记录：
{tx_text}

负债情况：
{liab_text}

请分析：
1. 消费结构是否合理
2. 是否有异常消费
3. 分类支出占比
4. 优化建议

用简洁中文回答，不超过300字。"""
        
        # 投资分析 — 远瞻
        investment_task = f"""你是 SilentBook 的投资分析 Agent。请分析以下财务数据，给出投资分析。

资产情况：
{assets_text}

交易记录：
{tx_text}

请分析：
1. 资产配置是否合理
2. 储蓄率如何
3. 投资风险评估
4. 资产配置建议

用简洁中文回答，不超过300字。"""
        
        # 综合建议 — 同时启动两个 agent
        consumption_task_coro = call_openclaw_agent(
            AGENT_MAP["consumption"], consumption_task, timeout=60
        )
        investment_task_coro = call_openclaw_agent(
            AGENT_MAP["investment"], investment_task, timeout=60
        )
        
        results = await asyncio.gather(consumption_task_coro, investment_task_coro, return_exceptions=True)
        
        consumption = results[0] if not isinstance(results[0], Exception) else f"消费分析失败: {results[0]}"
        investment = results[1] if not isinstance(results[1], Exception) else f"投资分析失败: {results[1]}"
        
        # 检查是否需要 fallback
        if AGENT_MODE == "auto" and ("无法连接" in consumption or "无法连接" in investment):
            mode_used = "local (fallback)"
            consumption = ""
            investment = ""
    
    if not consumption or not investment:
        # 本地 LLM 分析
        mode_used = "local"
        
        if not consumption:
            consumption = await call_llm(
                f"分析以下交易数据，给出消费分析（200字以内）：\n{tx_text}\n\n负债：\n{liab_text}",
                "你是 SilentBook 的消费分析 Agent。"
            )
        
        if not investment:
            investment = await call_llm(
                f"分析以下资产和交易数据，给出投资分析（200字以内）：\n资产：\n{assets_text}\n\n交易：\n{tx_text}",
                "你是 SilentBook 的投资分析 Agent。"
            )
    
    # 综合建议 — 本地生成（基于前两项分析结果）
    suggestion_prompt = f"""基于以下分析结果，给出综合财务建议：

消费分析：{consumption}

投资分析：{investment}

请给出：
1. 财务健康度评分（1-10）
2. 最需要改进的一点
3. 下一步行动建议

用简洁中文回答，不超过200字。"""
    
    suggestion = await call_llm(suggestion_prompt, "你是 SilentBook 的财务规划 Agent。")
    
    return AnalysisResponse(
        consumption=consumption,
        investment=investment,
        suggestion=suggestion,
        mode=mode_used
    )

# ===== API =====
@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest):
    """AI 分析 — 支持 local / openclaw / auto 三种模式"""
    try:
        return await do_analysis(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@app.post("/analyze/multi")
async def analyze_multi(request: AnalysisRequest):
    """多 Agent 模式 — 别名，等同 /analyze"""
    return await do_analysis(request)

@app.get("/agents")
async def list_agents():
    """列出可用的 agent"""
    return {
        "mode": AGENT_MODE,
        "agents": {
            "consumption": {
                "id": AGENT_MAP["consumption"],
                "name": "墨砚（财务总监）",
                "enabled": AGENT_MODE in ("openclaw", "auto"),
            },
            "investment": {
                "id": AGENT_MAP["investment"],
                "name": "远瞻（投资总监）",
                "enabled": AGENT_MODE in ("openclaw", "auto"),
            }
        },
        "local_llm": {
            "model": MODEL_NAME,
            "configured": bool(DASHSCOPE_API_KEY),
        }
    }

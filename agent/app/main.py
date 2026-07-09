from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import httpx
import os
from datetime import datetime

app = FastAPI(title="SilentBook Agent Engine", version="0.1.0")

MODEL_NAME = os.getenv("MODEL_NAME", "aliyun/glm-5.2")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1")

class AnalysisRequest(BaseModel):
    transactions: List[Dict]
    prompt: Optional[str] = None
    agent_config: Optional[dict] = None

class AnalysisResponse(BaseModel):
    consumption: str
    investment: str
    suggestion: str

@app.get("/")
async def root():
    return {"message": "SilentBook Agent Engine", "model": MODEL_NAME}

@app.get("/health")
async def health():
    return {"status": "ok"}

async def call_llm(prompt: str, system_prompt: str = "") -> str:
    """调用阿里云百炼 API"""
    if not DASHSCOPE_API_KEY:
        return "API Key 未配置"
    
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2000
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{DASHSCOPE_BASE_URL}/services/aigc/text-generation/generation",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            return result.get("output", {}).get("text", "")
        except Exception as e:
            return f"API 调用失败: {str(e)}"

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest):
    """
    单 Agent 默认模式：同时输出消费/投资/全局三个方向的建议
    """
    try:
        # 构建交易数据摘要
        transactions_summary = []
        for tx in request.transactions[:50]:  # 限制50条避免token过多
            transactions_summary.append(
                f"{tx.get('parsed_at', '')} | {tx.get('account', '')} | "
                f"{tx.get('category', '')} | {tx.get('transaction_type', '')} | "
                f"¥{tx.get('amount', 0)} | {tx.get('description', '')}"
            )
        
        tx_text = "\n".join(transactions_summary)
        
        # 消费分析
        consumption_prompt = f"""你是一个财务分析专家。请分析以下交易数据，给出消费分析：

交易记录：
{tx_text}

请从以下角度分析：
1. 消费结构是否合理
2. 是否有异常消费
3. 优化建议

用简洁的中文回答，不超过200字。"""
        
        consumption = await call_llm(consumption_prompt, "你是 SilentBook 的消费分析 Agent。")
        
        # 投资分析
        investment_prompt = f"""你是一个投资分析专家。请分析以下交易数据，给出投资分析：

交易记录：
{tx_text}

请从以下角度分析：
1. 储蓄率如何
2. 是否有投资行为
3. 投资建议

用简洁的中文回答，不超过200字。"""
        
        investment = await call_llm(investment_prompt, "你是 SilentBook 的投资分析 Agent。")
        
        # 综合建议
        suggestion_prompt = f"""你是一个财务规划专家。请基于以下交易数据，给出综合建议：

交易记录：
{tx_text}

请从以下角度给出建议：
1. 财务健康度
2. 需要改进的地方
3. 下一步行动建议

用简洁的中文回答，不超过200字。"""
        
        suggestion = await call_llm(suggestion_prompt, "你是 SilentBook 的财务规划 Agent。")
        
        return AnalysisResponse(
            consumption=consumption,
            investment=investment,
            suggestion=suggestion
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@app.post("/analyze/multi")
async def analyze_multi(request: AnalysisRequest):
    """
    多 Agent 模式：每个 Agent 独立分析（Phase 2）
    """
    return {"message": "Multi-agent mode - coming in Phase 2"}

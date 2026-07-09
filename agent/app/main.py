from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict
import httpx
import os

app = FastAPI(title="SilentBook Agent Engine", version="0.1.0")

MODEL_NAME = os.getenv("MODEL_NAME", "aliyun/glm-5.2")

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

@app.post("/analyze", response_model=AnalysisResponse)
async def analyze(request: AnalysisRequest):
    """
    单 Agent 默认模式：同时输出消费/投资/全局三个方向的建议
    """
    try:
        # TODO: 接入真实 LLM API
        # 临时返回固定文本
        return AnalysisResponse(
            consumption="本月消费节奏正常，建议关注未分类消费。",
            investment="定投正常执行，持仓收益稳定。",
            suggestion="控制非必要支出，保持定投节奏。"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@app.post("/analyze/multi")
async def analyze_multi(request: AnalysisRequest):
    """
    多 Agent 模式：每个 Agent 独立分析（Phase 2）
    """
    return {"message": "Multi-agent mode - coming in Phase 2"}

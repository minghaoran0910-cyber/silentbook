"""
实时推送模块
支持微信、飞书等渠道推送通知
"""

import httpx
import os
from typing import Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class NotificationPusher:
    """通知推送器"""
    
    def __init__(self):
        self.feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL")
        self.wechat_webhook = os.getenv("WECHAT_WEBHOOK_URL")
    
    async def push_to_feishu(self, title: str, content: str) -> bool:
        """推送到飞书"""
        if not self.feishu_webhook:
            logger.warning("飞书 webhook 未配置")
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {
                            "title": {
                                "tag": "plain_text",
                                "content": title
                            },
                            "template": "blue"
                        },
                        "elements": [
                            {
                                "tag": "markdown",
                                "content": content
                            }
                        ]
                    }
                }
                
                response = await client.post(
                    self.feishu_webhook,
                    json=payload,
                    timeout=10.0
                )
                response.raise_for_status()
                logger.info(f"飞书推送成功: {title}")
                return True
        except Exception as e:
            logger.error(f"飞书推送失败: {e}")
            return False
    
    async def push_to_wechat(self, title: str, content: str) -> bool:
        """推送到企业微信"""
        if not self.wechat_webhook:
            logger.warning("企业微信 webhook 未配置")
            return False
        
        try:
            async with httpx.AsyncClient() as client:
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": f"## {title}\n\n{content}"
                    }
                }
                
                response = await client.post(
                    self.wechat_webhook,
                    json=payload,
                    timeout=10.0
                )
                response.raise_for_status()
                logger.info(f"企业微信推送成功: {title}")
                return True
        except Exception as e:
            logger.error(f"企业微信推送失败: {e}")
            return False
    
    async def push_transaction(self, transaction: dict, channels: list = None) -> dict:
        """
        推送交易记录
        
        Args:
            transaction: 交易记录字典
            channels: 推送渠道列表，默认 ["feishu", "wechat"]
        """
        if channels is None:
            channels = ["feishu", "wechat"]
        
        # 构建消息内容
        amount = transaction.get("amount", 0)
        category = transaction.get("category", "未知")
        account = transaction.get("account", "未知")
        tx_type = transaction.get("transaction_type", "expense")
        description = transaction.get("description", "")
        parsed_at = transaction.get("parsed_at", datetime.now())
        
        type_emoji = "💰" if tx_type == "income" else "💸"
        type_text = "收入" if tx_type == "income" else "支出"
        
        title = f"{type_emoji} 新{type_text}记录"
        content = f"""
**金额**: ¥{amount:.2f}
**分类**: {category}
**账户**: {account}
**描述**: {description or '无'}
**时间**: {parsed_at}
"""
        
        results = {}
        
        if "feishu" in channels:
            results["feishu"] = await self.push_to_feishu(title, content)
        
        if "wechat" in channels:
            results["wechat"] = await self.push_to_wechat(title, content)
        
        return results


# 全局实例
pusher = NotificationPusher()

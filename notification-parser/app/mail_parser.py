"""
邮件通知解析器

通过 IMAP 轮询银行/支付平台的邮件通知，解析后存入交易记录。

配置环境变量：
- MAIL_IMAP_HOST: IMAP 服务器地址
- MAIL_IMAP_PORT: 端口（默认 993）
- MAIL_USERNAME: 邮箱地址
- MAIL_PASSWORD: 授权码
- MAIL_POLL_INTERVAL: 轮询间隔秒数（默认 300）
"""

from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional, List, Dict
import os
import logging
import asyncio

logger = logging.getLogger("mail-parser")
app = FastAPI(title="SilentBook Mail Parser", version="0.1.0")

IMAP_HOST = os.getenv("MAIL_IMAP_HOST", "")
IMAP_PORT = int(os.getenv("MAIL_IMAP_PORT", "993"))
MAIL_USER = os.getenv("MAIL_USERNAME", "")
MAIL_PASS = os.getenv("MAIL_PASSWORD", "")
POLL_INTERVAL = int(os.getenv("MAIL_POLL_INTERVAL", "300"))

# 邮件通知关键词映射
MAIL_KEYWORDS = {
    "招商银行": "cmb",
    "工商银行": "icbc",
    "建设银行": "ccb",
    "支付宝": "alipay",
    "微信支付": "wechat_pay",
    "财付通": "wechat_pay",
}

@app.get("/")
async def root():
    return {
        "message": "SilentBook Mail Parser",
        "configured": bool(IMAP_HOST and MAIL_USER and MAIL_PASS),
    }

@app.get("/health")
async def health():
    return {"status": "ok", "configured": bool(IMAP_HOST and MAIL_PASS)}

@app.post("/poll")
async def poll_mail():
    """手动触发邮件轮询"""
    if not IMAP_HOST or not MAIL_USER or not MAIL_PASS:
        return {"status": "skipped", "reason": "邮件未配置"}
    
    try:
        import imaplib
        import email
        from email.header import decode_header
        
        mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("inbox")
        
        # 搜索最近的未读邮件
        _, data = mail.search(None, "UNSEEN")
        mail_ids = data[0].split()
        
        results = []
        for mail_id in mail_ids[-20:]:  # 最多处理20封
            _, msg_data = mail.fetch(mail_id, "(RFC822)")
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            
            # 提取发件人、主题、正文
            subject = decode_header(msg["Subject"] or "")[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode("utf-8", errors="ignore")
            
            from_ = decode_header(msg["From"] or "")[0][0]
            if isinstance(from_, bytes):
                from_ = from_.decode("utf-8", errors="ignore")
            
            # 提取正文
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    ctype = part.get_content_type()
                    if ctype == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break
                    elif ctype == "text/html" and not body:
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
            else:
                body = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
            
            # 检查是否是银行/支付通知
            full_text = f"{subject} {from_} {body}"
            matched_source = None
            for keyword, source in MAIL_KEYWORDS.items():
                if keyword in full_text:
                    matched_source = source
                    break
            
            if matched_source:
                results.append({
                    "subject": subject,
                    "from": from_,
                    "source": matched_source,
                    "body": body[:500],
                })
        
        mail.logout()
        return {
            "status": "ok",
            "checked": len(mail_ids),
            "matched": len(results),
            "notifications": results
        }
        
    except Exception as e:
        logger.error(f"邮件轮询失败: {e}")
        return {"status": "error", "reason": str(e)}


@app.post("/parse")
async def parse_mail_notification(notification: dict):
    """解析单封邮件通知文本"""
    # 复用通知解析器的逻辑
    # 这里将邮件正文转发给通知解析器
    PARSER_URL = os.getenv("PARSER_API_URL", "http://localhost:6000")
    
    import httpx
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{PARSER_URL}/parse",
                json={
                    "title": notification.get("subject", ""),
                    "body": notification.get("body", ""),
                    "source": notification.get("source", "email"),
                },
                timeout=10.0
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "reason": str(e)}

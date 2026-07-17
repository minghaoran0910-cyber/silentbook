"""用户认证模块：注册/登录/JWT 验证"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import jwt
from bcrypt import hashpw, gensalt, checkpw
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db, User
from .tenant import set_tenant_user_id
from .schemas import UserRegister, UserLogin, UserResponse, TokenResponse, PasswordResetRequest, PasswordResetConfirm

router = APIRouter(prefix="/auth", tags=["auth"])

# 配置
APP_ENV = os.getenv("APP_ENV", "production").lower()
_INSECURE_JWT_SECRET = "silentbook-secret-change-in-production"
JWT_SECRET = os.getenv("JWT_SECRET", _INSECURE_JWT_SECRET)
if APP_ENV == "production" and JWT_SECRET == _INSECURE_JWT_SECRET:
    raise RuntimeError("JWT_SECRET must be configured with a strong value in production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "30"))

security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return hashpw(password.encode("utf-8"), gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """从 Bearer token 解析当前用户。token 缺失时返回 None（不报错）。"""
    token = credentials.credentials if credentials and credentials.credentials else request.cookies.get("auth_token")
    if not token:
        return None
    try:
        payload = jwt.decode(
            token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id).first()
    except (jwt.PyJWTError, ValueError):
        return None


async def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
    """需要登录才能访问的路由用这个依赖"""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请先登录",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    set_tenant_user_id(user.id)
    return user


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: UserRegister, response: Response, db: Session = Depends(get_db)):
    """用户注册（邮箱或手机号）"""
    # 检查邮箱是否已注册
    if data.email:
        existing = db.query(User).filter(User.email == data.email).first()
        if existing:
            raise HTTPException(status_code=409, detail="该邮箱已注册")
    # 检查手机号是否已注册
    if data.phone:
        existing = db.query(User).filter(User.phone == data.phone).first()
        if existing:
            raise HTTPException(status_code=409, detail="该手机号已注册")

    user = User(
        email=data.email,
        phone=data.phone,
        password_hash=hash_password(data.password),
        nickname=data.nickname,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_token(user)
    _set_auth_cookie(response, token)
    return TokenResponse(
        access_token=token if APP_ENV != "production" else "",
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, response: Response, db: Session = Depends(get_db)):
    """用户登录（邮箱或手机号）"""
    account = data.account.strip()
    # 自动判断是邮箱还是手机号
    if re.match(r"^1[3-9]\d{9}$", account):
        user = db.query(User).filter(User.phone == account).first()
    elif "@" in account:
        user = db.query(User).filter(User.email == account.lower()).first()
    else:
        # 尝试两种方式
        user = (
            db.query(User)
            .filter((User.email == account) | (User.phone == account))
            .first()
        )

    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    token = create_token(user)
    _set_auth_cookie(response, token)
    return TokenResponse(
        access_token=token if APP_ENV != "production" else "",
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user=UserResponse.model_validate(user),
    )


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "auth_token", token, httponly=True, secure=APP_ENV == "production",
        samesite="strict", max_age=JWT_EXPIRE_HOURS * 3600, path="/",
    )


@router.post("/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie("auth_token", path="/", httponly=True, secure=APP_ENV == "production", samesite="strict")


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(require_user)):
    """获取当前登录用户信息"""
    return user


# ===== 密码找回 =====

@router.post("/forgot-password")
def forgot_password(data: PasswordResetRequest, db: Session = Depends(get_db)):
    """请求密码重置：发送重置令牌到用户邮箱

    开发模式：直接返回令牌（不发送邮件）
    生产模式：通过 SMTP 发送重置邮件（需配置 SMTP_HOST）
    """
    account = data.account.strip()

    # 查找用户
    if re.match(r"^1[3-9]\d{9}$", account):
        user = db.query(User).filter(User.phone == account).first()
    elif "@" in account:
        user = db.query(User).filter(User.email == account.lower()).first()
    else:
        user = (
            db.query(User)
            .filter((User.email == account) | (User.phone == account))
            .first()
        )

    # 安全考虑：无论用户是否存在都返回相同消息（防止枚举攻击）
    if not user:
        return {"message": "如果该账号存在，重置链接已发送"}

    if not user.email:
        # 只绑定了手机号，无法发邮件
        return {"message": "该账号未绑定邮箱，请联系管理员重置密码"}

    # 生成重置令牌（JWT，有效期短）
    reset_payload = {
        "sub": str(user.id),
        "purpose": "password_reset",
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
    }
    reset_token = jwt.encode(reset_payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    # 尝试发送邮件
    smtp_host = os.getenv("SMTP_HOST")
    if smtp_host:
        _send_reset_email(user.email, reset_token, smtp_host)
        return {"message": "重置链接已发送到您的邮箱"}
    elif APP_ENV in ("development", "dev", "test"):
        # 显式开发/测试模式才允许把令牌返回给调用方
        return {
            "message": "开发模式：重置令牌已生成",
            "reset_token": reset_token,
            "expires_in": RESET_TOKEN_EXPIRE_MINUTES * 60,
        }
    else:
        # 生产环境绝不泄露重置令牌。
        logger = __import__("logging").getLogger("silentbook")
        logger.error("SMTP_HOST 未配置，无法发送密码重置邮件")
        return {"message": "如果该账号存在，重置链接已发送"}


@router.post("/reset-password")
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    """重置密码：验证令牌 + 设置新密码"""
    try:
        payload = jwt.decode(
            data.token, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="重置令牌已过期，请重新申请")
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="重置令牌无效")

    # 验证令牌用途
    if payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=400, detail="令牌用途不正确")

    user_id = int(payload.get("sub", 0))
    if not user_id:
        raise HTTPException(status_code=400, detail="令牌内容无效")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")

    # 设置新密码
    user.password_hash = hash_password(data.new_password)
    db.commit()

    return {"message": "密码重置成功，请使用新密码登录"}


@router.post("/dev-reset-password")
def dev_reset_password(data: dict, db: Session = Depends(get_db)):
    """开发模式重置密码；生产和未显式配置的环境始终禁用。"""
    if APP_ENV not in ("development", "dev"):
        raise HTTPException(status_code=403, detail="仅限开发模式使用")
    
    account = data.get("account", "").strip()
    new_password = data.get("password", "")
    if not account or not new_password or len(new_password) < 6:
        raise HTTPException(status_code=400, detail="需要提供 account 和 password(>=6位)")
    
    # 查找用户
    if re.match(r"^1[3-9]\d{9}$", account):
        user = db.query(User).filter(User.phone == account).first()
    elif "@" in account:
        user = db.query(User).filter(User.email == account.lower()).first()
    else:
        user = db.query(User).filter((User.email == account) | (User.phone == account)).first()
    
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    user.password_hash = hash_password(new_password)
    db.commit()
    return {"message": f"用户 {user.email or user.phone} 密码已重置"}


def _send_reset_email(to_email: str, reset_token: str, smtp_host: str):
    """通过 SMTP 发送密码重置邮件"""
    import smtplib
    from email.mime.text import MIMEText

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASS", "")
    from_email = os.getenv("SMTP_FROM", smtp_user)
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")

    reset_link = f"{frontend_url}/reset-password?token={reset_token}"

    body = f"""
    <h2>密码重置</h2>
    <p>您正在重置 SilentBook 账户密码。</p>
    <p>点击下方链接设置新密码（30 分钟内有效）：</p>
    <p><a href="{reset_link}">{reset_link}</a></p>
    <p>如果这不是您本人的操作，请忽略此邮件。</p>
    """

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = "SilentBook 密码重置"
    msg["From"] = from_email
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if smtp_user and smtp_pass:
            server.starttls()
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, to_email, msg.as_string())

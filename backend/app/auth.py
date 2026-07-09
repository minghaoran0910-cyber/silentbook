"""用户认证模块：注册/登录/JWT 验证"""
import os
import re
from datetime import datetime, timedelta
from typing import Optional

import jwt
from bcrypt import hashpw, gensalt, checkpw
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from .database import get_db, User
from .schemas import UserRegister, UserLogin, UserResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

# 配置
JWT_SECRET = os.getenv("JWT_SECRET", "silentbook-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

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
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """从 Bearer token 解析当前用户。token 缺失时返回 None（不报错）。"""
    if not credentials or not credentials.credentials:
        return None
    try:
        payload = jwt.decode(
            credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM]
        )
        user_id = int(payload.get("sub", 0))
        if not user_id:
            return None
        return db.query(User).filter(User.id == user_id).first()
    except (jwt.PyJWTError, ValueError):
        return None


def require_user(user: Optional[User] = Depends(get_current_user)) -> User:
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
    return user


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(data: UserRegister, db: Session = Depends(get_db)):
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
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(data: UserLogin, db: Session = Depends(get_db)):
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
    return TokenResponse(
        access_token=token,
        expires_in=JWT_EXPIRE_HOURS * 3600,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(user: User = Depends(require_user)):
    """获取当前登录用户信息"""
    return user

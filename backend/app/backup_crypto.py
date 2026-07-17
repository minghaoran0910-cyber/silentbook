"""Encrypted, owner-only backup file helpers."""
import gzip
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

def _fernet() -> Fernet:
    key = os.getenv("BACKUP_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY must be configured")
    return Fernet(key.encode())

def write_backup(path: Path, data: dict) -> None:
    raw = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
    encrypted = _fernet().encrypt(gzip.compress(raw))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(encrypted)

def read_backup(path: Path) -> dict:
    try:
        raw = gzip.decompress(_fernet().decrypt(path.read_bytes()))
    except InvalidToken as exc:
        raise ValueError("备份密钥错误或文件已损坏") from exc
    return json.loads(raw.decode("utf-8"))

import os
from pathlib import Path
from cryptography.fernet import Fernet
from app.backup_crypto import read_backup, write_backup

def test_encrypted_backup_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    target = tmp_path / "backup.json.gz.enc"
    payload = {"tables": {"transactions": [{"amount": "12.34"}]}}
    write_backup(target, payload)
    assert target.stat().st_mode & 0o777 == 0o600
    assert b"12.34" not in target.read_bytes()
    assert read_backup(target) == payload

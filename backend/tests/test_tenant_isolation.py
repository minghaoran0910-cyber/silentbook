"""Regression tests for the fail-closed ORM tenant boundary."""
import os
import sys

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough-for-tests")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, Transaction, User
from app.tenant import reset_tenant_user_id, set_tenant_user_id


engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=engine)


@pytest.fixture(autouse=True)
def database():
    Base.metadata.create_all(engine)
    session = TestingSession()
    session.add_all(
        [
            User(id=1, email="one@example.com", password_hash="unused"),
            User(id=2, email="two@example.com", password_hash="unused"),
        ]
    )
    session.commit()
    session.close()
    yield
    Base.metadata.drop_all(engine)


def add_transaction(user_id: int, description: str) -> int:
    token = set_tenant_user_id(user_id)
    session = TestingSession()
    try:
        transaction = Transaction(
            amount=10,
            category="test",
            account="cash",
            description=description,
            transaction_type="expense",
        )
        session.add(transaction)
        session.commit()
        return transaction.id
    finally:
        session.close()
        reset_tenant_user_id(token)


def test_users_only_read_their_own_rows():
    first_id = add_transaction(1, "first")
    second_id = add_transaction(2, "second")

    token = set_tenant_user_id(1)
    session = TestingSession()
    try:
        assert [row.id for row in session.query(Transaction).all()] == [first_id]
        assert session.query(Transaction).filter(Transaction.id == second_id).first() is None
    finally:
        session.close()
        reset_tenant_user_id(token)


def test_bulk_delete_is_tenant_scoped():
    add_transaction(1, "first")
    second_id = add_transaction(2, "second")

    token = set_tenant_user_id(1)
    session = TestingSession()
    try:
        assert session.query(Transaction).delete() == 1
        session.commit()
    finally:
        session.close()
        reset_tenant_user_id(token)

    token = set_tenant_user_id(2)
    session = TestingSession()
    try:
        assert session.query(Transaction).filter(Transaction.id == second_id).one()
    finally:
        session.close()
        reset_tenant_user_id(token)


def test_missing_tenant_context_fails_closed():
    add_transaction(1, "private")
    session = TestingSession()
    try:
        assert session.query(Transaction).all() == []
    finally:
        session.close()

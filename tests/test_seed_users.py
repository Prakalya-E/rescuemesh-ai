
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app import models
from backend.app.database import Base
from backend.app.models import User
from backend.app.security import pwd
from scripts.seed_users import upsert_user


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with sessionmaker(bind=engine)() as session:
        yield session


def test_creates_user_with_hashed_password(db):
    assert upsert_user(
        db, "asha", "coordinator", "a-long-password"
    ) == "created"

    user = db.query(User).one()

    assert user.role == "coordinator"
    assert user.password_hash != "a-long-password"
    assert pwd.verify("a-long-password", user.password_hash)


def test_duplicate_user_needs_reset(db):
    upsert_user(db, "asha", "viewer", "a-long-password")

    with pytest.raises(ValueError, match="already exists"):
        upsert_user(db, "asha", "viewer", "another-password")


def test_reset_changes_role_and_password(db):
    upsert_user(db, "asha", "viewer", "a-long-password")

    assert upsert_user(
        db, "asha", "auditor", "new-long-password", reset=True
    ) == "updated"

    user = db.query(User).one()

    assert user.role == "auditor"
    assert pwd.verify("new-long-password", user.password_hash)


def test_rejects_old_or_unknown_role(db):
    with pytest.raises(ValueError, match="role"):
        upsert_user(db, "asha", "admin", "a-long-password")


def test_rejects_short_password(db):
    with pytest.raises(ValueError, match="at least"):
        upsert_user(db, "asha", "viewer", "short")

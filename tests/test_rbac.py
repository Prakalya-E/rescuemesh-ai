
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import models, models_live
from backend.app.database import Base, get_db
from backend.app.main import app
from backend.app.models import User
from backend.app.roles import (
    ALL_ROLES, COORDINATOR, FIELD_WORKER, VIEWER, AUDITOR
)
from backend.app.security import pwd

PASSWORD = "Test-pass-123"

REC = {
    "hazard": "flood",
    "district": "Cachar",
    "state": "Assam",
    "risk_level": "severe",
    "action": "Pre-position boats and open relief camps"
}


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

    Base.metadata.create_all(engine)

    Session = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False
    )

    with Session() as db:
        for role in ALL_ROLES:
            db.add(
                User(
                    username=role,
                    password_hash=pwd.hash(PASSWORD),
                    role=role
                )
            )
        db.commit()

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db

    yield TestClient(app)

    app.dependency_overrides.clear()


def auth(client, role):
    r = client.post(
        "/auth/login",
        data={"username": role, "password": PASSWORD}
    )

    assert r.status_code == 200, r.text
    assert r.json()["role"] == role

    return {
        "Authorization": "Bearer " + r.json()["access_token"]
    }


def create_rec(client):
    r = client.post(
        "/recommendations",
        headers=auth(client, COORDINATOR),
        json=REC
    )

    assert r.status_code == 200, r.text
    return r.json()["id"]


def decide(client, rid, role, approve=True):
    return client.post(
        f"/recommendations/{rid}/decision",
        headers=auth(client, role),
        json={"approve": approve}
    )


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_log_in_and_see_itself(client, role):
    r = client.get("/me", headers=auth(client, role))
    assert r.status_code == 200 and r.json()["role"] == role


def test_wrong_password_is_rejected_and_audited(client):
    assert client.post(
        "/auth/login",
        data={"username": COORDINATOR, "password": "nope"}
    ).status_code == 401

    events = [
        e["event"]
        for e in client.get(
            "/audit", headers=auth(client, AUDITOR)
        ).json()
    ]

    assert "login_failed" in events


@pytest.mark.parametrize(
    "role", [FIELD_WORKER, VIEWER, AUDITOR]
)
def test_only_coordinator_can_create(client, role):
    assert client.post(
        "/recommendations",
        headers=auth(client, role),
        json=REC
    ).status_code == 403


def test_coordinator_can_approve(client):
    rid = create_rec(client)
    r = decide(client, rid, COORDINATOR, approve=True)

    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_coordinator_can_reject(client):
    rid = create_rec(client)

    assert decide(
        client, rid, COORDINATOR, approve=False
    ).json()["status"] == "rejected"


@pytest.mark.parametrize(
    "role", [FIELD_WORKER, VIEWER, AUDITOR]
)
def test_others_cannot_decide_and_status_stays_pending(client, role):
    rid = create_rec(client)

    assert decide(client, rid, role).status_code == 403

    recs = client.get(
        "/recommendations",
        headers=auth(client, COORDINATOR)
    ).json()

    assert [
        r["status"] for r in recs if r["id"] == rid
    ] == ["pending"]


def test_double_decision_is_blocked(client):
    rid = create_rec(client)

    assert decide(client, rid, COORDINATOR).status_code == 200

    assert decide(
        client, rid, COORDINATOR, approve=False
    ).status_code == 409


def test_unknown_recommendation_is_404(client):
    assert decide(
        client, 9999, COORDINATOR
    ).status_code == 404


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_list_recommendations(client, role):
    assert client.get(
        "/recommendations",
        headers=auth(client, role)
    ).status_code == 200


@pytest.mark.parametrize(
    "role,expected",
    [
        (COORDINATOR, 200),
        (AUDITOR, 200),
        (FIELD_WORKER, 403),
        (VIEWER, 403)
    ]
)
def test_audit_log_access(client, role, expected):
    assert client.get(
        "/audit", headers=auth(client, role)
    ).status_code == expected


def test_decision_is_written_to_audit_log(client):
    rid = create_rec(client)
    decide(client, rid, COORDINATOR)

    events = [
        e["event"]
        for e in client.get(
            "/audit", headers=auth(client, AUDITOR)
        ).json()
    ]

    assert (
        "recommendation_created" in events
        and "recommendation_approved" in events
    )


@pytest.mark.parametrize(
    "path",
    ["/me", "/recommendations", "/audit", "/hazards"]
)
def test_endpoints_require_login(client, path):
    assert client.get(path).status_code == 401

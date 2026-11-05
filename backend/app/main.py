
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import User, Recommendation, AuditLog
from .roles import COORDINATOR, AUDITOR
from .security import pwd, make_token, current_user, require_roles
from .routers import hazards, geo, live, risk


def audit(db: Session, user_id, event: str, detail: str = ""):
    db.add(AuditLog(user_id=user_id, event=event, detail=detail))
    db.commit()


app = FastAPI(title="RescueMesh AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in settings.CORS_ORIGINS.split(",")
        if o.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(hazards.router)
app.include_router(geo.router)
app.include_router(live.router)
app.include_router(risk.router)


class RecIn(BaseModel):
    hazard: str = ""
    district: str
    state: str
    risk_level: str
    action: str


class DecisionIn(BaseModel):
    approve: bool


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login")
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = db.scalar(
        select(User).where(User.username == form.username)
    )

    if not user or not pwd.verify(form.password, user.password_hash):
        audit(db, None, "login_failed", form.username)
        raise HTTPException(401, "Wrong username or password")

    audit(db, user.id, "login")

    return {
        "access_token": make_token(user),
        "token_type": "bearer",
        "role": user.role
    }


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role
    }


@app.post("/recommendations")
def create_rec(
    body: RecIn,
    user: User = Depends(require_roles(COORDINATOR)),
    db: Session = Depends(get_db)
):
    rec = Recommendation(
        **body.model_dump(),
        created_by=user.id
    )

    db.add(rec)
    db.commit()
    db.refresh(rec)

    audit(db, user.id, "recommendation_created", f"id={rec.id}")

    return rec


@app.get("/recommendations")
def list_recs(
    status: str | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    q = select(Recommendation).order_by(
        Recommendation.id.desc()
    )

    if status:
        q = q.where(Recommendation.status == status)

    return db.scalars(q).all()


@app.post("/recommendations/{rec_id}/decision")
def decide(
    rec_id: int,
    body: DecisionIn,
    user: User = Depends(require_roles(COORDINATOR)),
    db: Session = Depends(get_db)
):
    rec = db.get(Recommendation, rec_id)

    if not rec:
        raise HTTPException(404, "Not found")

    if rec.status != "pending":
        raise HTTPException(409, f"Already {rec.status}")

    rec.status = "approved" if body.approve else "rejected"
    rec.decided_by = user.id

    db.commit()

    audit(db, user.id, f"recommendation_{rec.status}", f"id={rec.id}")

    return rec


@app.get("/audit")
def get_audit(
    user: User = Depends(require_roles(COORDINATOR, AUDITOR)),
    db: Session = Depends(get_db)
):
    return db.scalars(
        select(AuditLog).order_by(AuditLog.id.desc()).limit(200)
    ).all()


@app.get("/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness: can this instance serve requests?"""

    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from .routers.hazards import OUT

    checks = {}

    try:
        db.execute(text("select 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"

    checks["hazard_tables"] = (
        "ok" if (OUT / "all_hazards_long.csv").exists()
        else "missing"
    )

    ok = (
        checks["database"] == "ok"
        and checks["hazard_tables"] == "ok"
    )

    return JSONResponse(
        {"status": "ready" if ok else "not_ready", **checks},
        status_code=200 if ok else 503
    )

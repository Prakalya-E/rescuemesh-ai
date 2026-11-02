"""Run from D:\\rescuemesh:  python setup_backend.py
Writes the full RescueMesh backend (auth, roles, approval gate, audit log, hazards API)
and a smoke test, then runs the test."""
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
FILES = {}

FILES["backend/__init__.py"] = ""
FILES["backend/app/__init__.py"] = ""
FILES["backend/app/routers/__init__.py"] = ""
FILES["backend/app/services/__init__.py"] = ""

FILES["backend/app/config.py"] = r'''from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./rescuemesh.db"
    SECRET_KEY: str = "dev-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
'''

FILES["backend/app/database.py"] = r'''from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings

args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=args)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
'''

FILES["backend/app/models.py"] = r'''from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from .database import Base


def now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20))  # analyst | commander | admin


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    hazard: Mapped[str] = mapped_column(String(30), default="")
    district: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(100))
    risk_level: Mapped[str] = mapped_column(String(20))
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event: Mapped[str] = mapped_column(String(100))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
'''

FILES["backend/app/security.py"] = r'''from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .config import settings
from .database import get_db
from .models import User

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2 = OAuth2PasswordBearer(tokenUrl="/auth/login")
ALGO = "HS256"


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode({"sub": str(user.id), "role": user.role, "exp": exp},
                      settings.SECRET_KEY, algorithm=ALGO)


def current_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        uid = int(jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGO])["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(401, "Invalid or expired token")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "User not found")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Requires role: {', '.join(roles)}")
        return user
    return dep
'''

FILES["backend/app/routers/hazards.py"] = r'''from pathlib import Path
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from ..security import current_user

OUT = Path(__file__).resolve().parents[3] / "data" / "processed" / "hazards"
router = APIRouter(prefix="/hazards", tags=["hazards"], dependencies=[Depends(current_user)])
_cache = {}


def long_table() -> pd.DataFrame:
    if "t" not in _cache:
        _cache["t"] = pd.read_csv(OUT / "all_hazards_long.csv").fillna("")
    return _cache["t"]


@router.get("")
def summary():
    t = long_table()
    return t.groupby(["hazard", "risk_level"]).size().unstack(fill_value=0).to_dict("index")


@router.get("/district/{name}")
def district(name: str):
    t = long_table()
    r = t[t.district.str.lower() == name.lower()]
    if r.empty:
        raise HTTPException(404, "District not found")
    return r.to_dict("records")


@router.get("/{hazard}")
def by_hazard(hazard: str, state: str | None = None, level: str | None = None, limit: int = 100):
    t = long_table()
    t = t[t.hazard == hazard]
    if t.empty:
        raise HTTPException(404, "Unknown hazard")
    if state:
        t = t[t.state_name.str.lower() == state.lower()]
    if level:
        t = t[t.risk_level == level]
    return t.sort_values("risk_score", ascending=False).head(limit).to_dict("records")
'''

FILES["backend/app/main.py"] = r'''from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from .database import Base, engine, get_db, SessionLocal
from .models import User, Recommendation, AuditLog
from .security import pwd, make_token, current_user, require_roles
from .routers import hazards


def audit(db: Session, user_id, event: str, detail: str = ""):
    db.add(AuditLog(user_id=user_id, event=event, detail=detail))
    db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        if not db.scalar(select(User).limit(1)):
            for name, role in [("admin", "admin"), ("analyst", "analyst"), ("commander", "commander")]:
                db.add(User(username=name, password_hash=pwd.hash(name + "123"), role=role))
            db.commit()
    yield


app = FastAPI(title="RescueMesh AI", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(hazards.router)


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
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == form.username))
    if not user or not pwd.verify(form.password, user.password_hash):
        audit(db, None, "login_failed", form.username)
        raise HTTPException(401, "Wrong username or password")
    audit(db, user.id, "login")
    return {"access_token": make_token(user), "token_type": "bearer", "role": user.role}


@app.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@app.post("/recommendations")
def create_rec(body: RecIn, user: User = Depends(require_roles("analyst", "admin")),
               db: Session = Depends(get_db)):
    rec = Recommendation(**body.model_dump(), created_by=user.id)
    db.add(rec)
    db.commit()
    db.refresh(rec)
    audit(db, user.id, "recommendation_created", f"id={rec.id}")
    return rec


@app.get("/recommendations")
def list_recs(status: str | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    q = select(Recommendation).order_by(Recommendation.id.desc())
    if status:
        q = q.where(Recommendation.status == status)
    return db.scalars(q).all()


@app.post("/recommendations/{rec_id}/decision")
def decide(rec_id: int, body: DecisionIn, user: User = Depends(require_roles("commander")),
           db: Session = Depends(get_db)):
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
def get_audit(user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    return db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(200)).all()
'''

FILES["tests/smoke.py"] = r'''from fastapi.testclient import TestClient
from backend.app.main import app


def login(c, u):
    r = c.post("/auth/login", data={"username": u, "password": u + "123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


with TestClient(app) as c:
    a, m = login(c, "analyst"), login(c, "commander")
    r = c.post("/recommendations", headers=a, json={
        "hazard": "flood", "district": "Cachar", "state": "Assam",
        "risk_level": "severe", "action": "Pre-position boats and open relief camps"})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    print("analyst can create:          OK")
    assert c.post(f"/recommendations/{rid}/decision", headers=a, json={"approve": True}).status_code == 403
    print("analyst cannot approve:      OK")
    r = c.post(f"/recommendations/{rid}/decision", headers=m, json={"approve": True})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    print("commander can approve:       OK")
    assert c.post(f"/recommendations/{rid}/decision", headers=m, json={"approve": False}).status_code == 409
    print("double decision blocked:     OK")
    assert c.get("/hazards").status_code == 401
    print("hazards need login:          OK")
    s = c.get("/hazards", headers=a).json()
    print("hazards available:", sorted(s))
    top = c.get("/hazards/flood?state=Assam&limit=3", headers=a).json()
    print("top Assam flood:", [(x["district"], x["risk_level"]) for x in top])
    adm = login(c, "admin")
    print("audit events:", [x["event"] for x in c.get("/audit", headers=adm).json()][:6])
print("ALL BACKEND CHECKS PASSED")
'''

for rel, text in FILES.items():
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    print("wrote", rel)

env = dict(**__import__("os").environ, PYTHONPATH=str(ROOT))
print("\nRunning smoke test...\n")
sys.exit(subprocess.call([sys.executable, "tests/smoke.py"], env=env, cwd=ROOT))

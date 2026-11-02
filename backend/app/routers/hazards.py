from pathlib import Path
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

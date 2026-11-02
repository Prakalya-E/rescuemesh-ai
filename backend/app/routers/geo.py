from fastapi import APIRouter, Depends, HTTPException, Query
from ..security import current_user
from ..services import geo

router = APIRouter(prefix="/geo", tags=["geo"], dependencies=[Depends(current_user)])


@router.get("/nearby")
def nearby(kind: str = "hospital", k: int = 5, district: str | None = None, state: str | None = None,
           lat: float | None = Query(default=None, ge=-90, le=90),
           lon: float | None = Query(default=None, ge=-180, le=180), path: bool = False):
    if kind not in geo.FAC_FILES:
        raise HTTPException(400, f"kind must be one of {sorted(geo.FAC_FILES)}")
    if (lat is None) != (lon is None):
        raise HTTPException(400, "Provide both lat and lon together")
    if lat is None or lon is None:
        if not district:
            raise HTTPException(400, "Give either district or lat+lon")
        try:
            lat, lon = geo.district_origin(district, state)
        except KeyError as e:
            raise HTTPException(404, str(e))
    return geo.nearby(lat, lon, kind, k=max(1, min(k, 20)), with_path=path)

"""Risk assessment for a point location. Authenticated like the other routers."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..security import current_user
from ..services import risk_service
from ..services.geospatial_service import get_locator

router = APIRouter(prefix="/risk", tags=["risk"], dependencies=[Depends(current_user)])


class PredictIn(BaseModel):
    latitude: float = Field(ge=6.0, le=38.0, description="India region box")
    longitude: float = Field(ge=68.0, le=98.0, description="India region box")


@router.post("/predict")
def predict(body: PredictIn, db: Session = Depends(get_db)):
    """District hazard scores plus nearby live signals. Relative rankings, not warnings."""
    try:
        found = get_locator().locate(body.latitude, body.longitude)
    except FileNotFoundError as e:
        raise HTTPException(503, str(e))
    if found is None:
        raise HTTPException(404, "No Indian district boundary contains this point (offshore or outside India).")
    district, state = found
    return risk_service.assess(db, body.latitude, body.longitude, district, state)

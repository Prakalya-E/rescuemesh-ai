import json
import pytest
from backend.app.services.geospatial_service import DistrictLocator, haversine_km


def square(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


@pytest.fixture()
def locator(tmp_path):
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"district": "Alpha", "state_name": "S1"},
         "geometry": {"type": "Polygon", "coordinates": [square(70, 10, 75, 15)]}},
        {"type": "Feature", "properties": {"district": "Beta", "state_name": "S2"},      # polygon with a hole
         "geometry": {"type": "MultiPolygon", "coordinates": [[square(80, 20, 90, 30), square(83, 23, 87, 27)]]}},
    ]}
    p = tmp_path / "d.geojson"
    p.write_text(json.dumps(gj), encoding="utf-8")
    return DistrictLocator(p)


def test_haversine_known_distance_and_zero():
    assert haversine_km(28.61, 77.21, 28.61, 77.21) == 0
    assert 1100 < haversine_km(28.61, 77.21, 19.07, 72.88) < 1200      # Delhi -> Mumbai is about 1,150 km


def test_locate_inside_hole_and_outside(locator):
    assert locator.locate(12, 72) == ("Alpha", "S1")                    # lat 12, lon 72
    assert locator.locate(21, 81) == ("Beta", "S2")
    assert locator.locate(25, 85) is None                              # inside Beta's hole
    assert locator.locate(40, 100) is None                             # nowhere
    assert locator.locate(12, 79) is None                              # between the two districts


def test_missing_boundary_file_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        DistrictLocator(tmp_path / "nope.geojson")

from fastapi.testclient import TestClient
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

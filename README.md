# RescueMesh AI

AI-powered disaster assessment and response support system.
District-level hazard risk, live data ingestion, geospatial routing to hospitals and shelters, and a human-approval workflow with an audit log.

## Structure

| Folder | Purpose |
|---|---|
| `backend/` | FastAPI app (auth, roles, hazards, geo, live, risk) |
| `ml/` | Hazard and risk model scripts |
| `scripts/` | Data building and ingestion tools |
| `tests/` | Pytest suite |
| `frontend/` | Next.js dashboard |
| `docs/` | Presentation and design notes |

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt -r ml/requirements.txt
copy .env.example .env
python -m pytest -q
uvicorn backend.app.main:app --reload
```

API docs: http://localhost:8000/docs

## Status

Backend, hazard risk models, live ingestion and geospatial routing are built.
Computer vision, RAG, the decision layer and the full dashboard are in progress.
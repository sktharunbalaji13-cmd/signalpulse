# SignalPulse

Real-time multi-source information intelligence — one pulse on any topic.

**Current status:** M0 — Engineering Scaffold

## Technology stack

- **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, httpx, SQLAlchemy 2.0
- **Frontend:** React, Vite, TypeScript
- **Quality:** pytest, ruff, GitHub Actions CI

## Local setup

Prerequisites: Python 3.11+ and Node.js 20+.

### Backend

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
uvicorn app.main:app --reload
```

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### Tests

```powershell
cd backend
pytest
```

### Lint

```powershell
cd backend
ruff check .
```

## Current limitations

- No search functionality yet — M0 only establishes the runnable scaffold.
- No external API integrations, no adapters, no ranking, no deduplication, no database tables, no deployment.
- `.env.example` contains placeholders only; no real API keys exist in the repository.

## Architecture

See [PROJECT_SPEC.md](PROJECT_SPEC.md) for the full architectural contract, source validation report, and roadmap.
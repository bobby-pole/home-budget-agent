# Technical Instructions for AI Agents

This file contains the technical configuration, architecture, and commands for the `home-budget-agent` project. It is intended for any AI agent working in this repository. It focuses strictly on technical implementation details.

## Commands

### Backend
- Start (dev): `docker-compose up --build -d`
- View logs: `docker-compose logs -f`
- Stop: `docker-compose down`

### Frontend
- Install dependencies: `cd frontend && npm install`
- Dev server: `npm run dev` (http://localhost:5173)
- Production build: `npm run build`
- Linter: `npm run lint`

### Database Migrations (Alembic)
- Generate migration: `docker-compose exec backend alembic revision --autogenerate -m "description"`
- Apply migrations: `docker-compose exec backend alembic upgrade head`
- Rollback one step: `docker-compose exec backend alembic downgrade -1`

### Production (VPS)
- Build frontend: `cd frontend && npm run build`
- Run container: `docker-compose -f docker-compose.prod.yml up --build -d`

## Architecture

- **Dev**: Two services. FastAPI in Docker (port 8000) + Vite dev server (port 5173). Vite proxies `/api` to `localhost:8000`.
- **Prod**: Single container (`Dockerfile.vps`) — FastAPI serves the React build as static files on port 8080.

## Tech Stack
- **Backend**: FastAPI + SQLModel (Pydantic v2) + SQLite + Alembic
- **Frontend**: React 19 + Vite + TypeScript + TanStack Query + Shadcn/UI + Tailwind v4
- **Auth**: JWT (`python-jose`) + bcrypt (`passlib`) — 7-day tokens
- **AI**: GPT-4o-mini via OpenAI vision API (receipt OCR)
- **Deploy**: VPS, Docker

## Key Files

### Backend
- `backend/app/models.py` — SQLModel tables + Pydantic DTOs
- `backend/app/api.py` — all routes under `/api`
- `backend/app/services.py` — AIService (OpenAI)
- `backend/app/database.py` — engine, session dependency
- `backend/app/auth.py` — JWT utilities, `get_current_user`

### Frontend
- `frontend/src/lib/api.ts` — Axios client + all API functions
- `frontend/src/types.ts` — shared TypeScript types
- `frontend/src/pages/` — page components
- `frontend/src/components/dashboard/` — feature components
- `frontend/src/components/ui/` — Shadcn primitives (**do not modify**)
- `frontend/src/context/AuthContext.tsx` — auth state
- `@` path alias → `frontend/src/`

## Technical Notes & Guidelines

- **Zod v4**: Use `z.email()` not `z.string().email()` (deprecated).
- **bcrypt**: Pin `bcrypt>=3.0.0,<4.0.0` — v4 is incompatible with passlib.
- **Shadcn/UI**: Never modify `src/components/ui/` — changes are lost on reinstall.
- **State Management**: Use TanStack Query for all server state (`useQuery` for fetching, `useMutation` for writes with cache invalidation).
- **Commits**: Never auto-commit changes. The owner will review and commit manually.
- **Language**: English for code, variable names, and comments.

## Environment setup (.env)

Create a `.env` file in the project root:
```env
OPENAI_API_KEY=your_api_key_here
ENVIRONMENT=development
SECRET_KEY=your_jwt_secret_here
```

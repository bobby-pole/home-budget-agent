# CLAUDE.md

Project instructions for Claude Code. Read this file at the start of every session.

---

## AI Assistant Role

You are the **Tech Lead and CTO** of this project. Your responsibilities:

- Lead technical and business discussions in dialogue form — ask questions, consult decisions, don't execute autonomously
- Maintain project documentation in `docs/` after every important conversation
- Create GitHub issues directly (visible `gh` CLI calls) — never through subagents
- Delegate implementation work to specialized subagents
- Show full output from agents — never summarize or truncate their responses

**Language**: Polish in all conversations with the owner. English in code and comments.

---

## Workflow — Every Implementation Task

```
Owner: "start issue #X"
  → Run project-manager agent (alignment check)
  → If PASSED: create branch → delegate to backend-dev or frontend-dev
  → Owner reviews changes in IDE
  → Owner: "OK" → create PR (or owner does it manually)
  → Owner provides PR number → run code-reviewer agent
```

### Branch naming
```bash
git checkout -b feat/<issue-number>-short-description
# example: feat/114-add-alembic
```

---

## GitHub-First Rule

**No implementation without a GitHub issue.** Every new idea, feature, or technical task must become an issue before work starts.

Process:
1. Propose issue to owner — full title + body in console
2. Wait for approval
3. Create issue directly via `gh` CLI
4. Link to appropriate epic

### Issue format
```markdown
**Epic:** #<number> <Epic name>
**Priority:** P0 | P1 | P2
**Depends on:** #<number> (description) — optional

## Description
...

## Acceptance Criteria
- [ ] ...
```

### Title prefixes
`[Backend]` / `[Frontend]` / `[Backend/Frontend]` / `Epic:`

### Priorities
- **P0** — blocker, nothing works without this
- **P1** — core value, user needs this for daily use
- **P2** — important but not blocking

---

## Subagents

| Agent | When to use |
|-------|-------------|
| `project-manager` | Before every implementation task — checks alignment with project docs |
| `backend-dev` | FastAPI, SQLModel, Alembic, Python implementation |
| `frontend-dev` | React, TypeScript, Tailwind, Shadcn/UI implementation |
| `code-reviewer` | On owner's request, after providing PR number |
| `security-analyst` | On owner's request, security audits |

---

## Project Documentation

Maintained by Tech Lead (Claude) in `docs/`:
- `business-context.md` — goals, target user, value hypotheses, competition
- `roadmap.md` — priorities and plan
- `project-analysis.md` — architecture, diagrams, technical state
- `decisions-log.md` — log of architectural and product decisions

**Update these files after every conversation that changes priorities, architecture, or product direction.**

---

## Commands

### Backend
```bash
docker-compose up --build -d   # Start with hot reload
docker-compose logs -f          # View logs
docker-compose down             # Stop
```

### Frontend
```bash
cd frontend
npm install       # Install dependencies
npm run dev       # Dev server at http://localhost:5173
npm run build     # Production build
npm run lint      # ESLint
```

### Database migrations (Alembic)
```bash
# Generate migration after model change
docker-compose exec backend alembic revision --autogenerate -m "description"

# Apply migrations
docker-compose exec backend alembic upgrade head

# Rollback one step
docker-compose exec backend alembic downgrade -1
```

### Production (VPS)
```bash
cd frontend && npm run build
docker-compose -f docker-compose.prod.yml up --build -d
```

---

## Architecture

**Dev**: two services — FastAPI in Docker (port 8000) + Vite dev server (port 5173). Vite proxies `/api` to `localhost:8000`.

**Prod**: single container (`Dockerfile.vps`) — FastAPI serves React build as static files on port 8080.

### Stack
- **Backend**: FastAPI + SQLModel (Pydantic v2) + SQLite + Alembic
- **Frontend**: React 19 + Vite + TypeScript + TanStack Query + Shadcn/UI + Tailwind v4
- **Auth**: JWT (`python-jose`) + bcrypt (`passlib`) — 7-day tokens
- **AI**: GPT-4o-mini via OpenAI vision API (receipt OCR)
- **Deploy**: Hetzner VPS, Docker

### Key files — Backend
- `backend/app/models.py` — SQLModel tables + Pydantic DTOs
- `backend/app/api.py` — all routes under `/api`
- `backend/app/services.py` — AIService (OpenAI)
- `backend/app/database.py` — engine, session dependency
- `backend/app/auth.py` — JWT utilities, `get_current_user`

### Key files — Frontend
- `frontend/src/lib/api.ts` — Axios client + all API functions
- `frontend/src/types.ts` — shared TypeScript types
- `frontend/src/pages/` — page components
- `frontend/src/components/dashboard/` — feature components
- `frontend/src/components/ui/` — Shadcn primitives (**do not modify**)
- `frontend/src/context/AuthContext.tsx` — auth state

`@` path alias → `frontend/src/`

### State management
TanStack Query for all server state. `useQuery` for fetching, `useMutation` for writes with cache invalidation.

### Auth flow
- `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`
- All `/api/transactions` and `/api/budget` require Bearer token
- Axios interceptor adds token; 401 → clearAuth + redirect to `/login`
- localStorage keys: `budget_token`, `budget_user`

---

## Tech Stack Notes

- **Zod v4**: use `z.email()` not `z.string().email()` (deprecated)
- **bcrypt**: pin `bcrypt>=3.0.0,<4.0.0` — v4 incompatible with passlib
- **Shadcn/UI**: never modify `src/components/ui/` — changes are lost on reinstall
- **Commits and pushes**: owner does manually — never ask to auto-commit

---

## Environment Setup

Create `.env` in project root:
```env
OPENAI_API_KEY=your_api_key_here
ENVIRONMENT=development
SECRET_KEY=your_jwt_secret_here
```

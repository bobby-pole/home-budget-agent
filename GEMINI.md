# GEMINI.md

Project instructions for Gemini CLI. Read this file at the start of every session.

---

## AI Assistant Role

You are the **Tech Lead and CTO** of this project. Your responsibilities:

- Lead technical and business discussions in dialogue form — ask questions, consult decisions, don't execute autonomously
- Maintain project documentation in `docs/` after every important conversation
- Create GitHub issues directly (visible `gh` CLI calls)
- Show full output — never summarize or truncate results
- **Save important new details during the session** — decisions, surprises, constraints, confirmed approaches worth remembering

**Language**: Polish in all conversations with the owner. English in code and comments.

**Git commits**: Never add `Co-Authored-By` or any AI authorship attribution to commit messages — commits belong solely to the owner.

---

## Specialized Roles

Gemini CLI does not have a subagent system. When the owner requests a specific role, adopt it explicitly and announce the switch:

| Role | When | Behavior |
|------|------|----------|
| **Project Manager** | Before every implementation task | Read `docs/`, verify alignment. Output ✅ PASSED or 🔴 BLOCKED. |
| **Backend Developer** | Implementing FastAPI/Python tasks | Correctness-focused, follow existing patterns, output structured change summary. |
| **Frontend Developer** | Implementing React/TypeScript tasks | Never modify `src/components/ui/`. TanStack Query for server state. |
| **Code Reviewer** | After owner provides PR number | `gh pr diff`, check security + correctness + conventions. Structured report. |
| **Security Analyst** | Security audits | Read-only, OWASP Top 10, auth/authz, input validation. Severity-graded findings. |

Announce role switches: _"Switching to [Role] mode."_

---

## Project

**Rachownik** — open-core household budgeting app for the Polish market. Envelope budgeting (YNAB-style) + AI receipt scanning with per-item categorization. Full business context: `docs/strategy/master-business-adr.md`.

---

## Architecture Philosophy

**"Less AI where possible, AI only where truly necessary."**

LLMs are expensive, non-deterministic tools of last resort. Hierarchy of data source quality:

| Level | Source | Time | Cost |
|-------|--------|------|------|
| 1 | Structured API (e-Paragon, PSD2) | 100-300ms | 0/low |
| 2 | PDF with text layer, CSV | 50-200ms | 0 |
| 3 | OCR + deterministic parser | 500-1500ms | low |
| 4 | OCR + AI structurization | 2-5s | high |
| 5 | Vision LLM directly | 3-10s | very high |

Every code change should aim to reach the highest possible level for the given input source.

---

## Critical Implementation Rules

- **NEVER chunk images** — causes hallucinations and duplicates. Whole receipt → single OCR call, then segment text deterministically.
- **Sum validation is mandatory** — `sum(items.total_after_discount) == receipt.total` (±0.01 PLN tolerance).
- **Cache-first for categorization** — rapidfuzz fuzzy lookup (threshold 85%) before any AI call.
- **Decimal arithmetic** for all monetary amounts — NEVER float.
- **SHA256 deduplication** — re-uploading same file = no-op.
- **OCR/AI must NOT block the upload endpoint** — use background tasks.

---

## What to AVOID

- **Image chunking** — causes duplicates
- **GPT-4 Vision with 512x512 tiling** — loses coherence on long receipts
- **Flat text concatenation from Vision** — loses column structure, use line reconstruction
- **AI for structuring known formats** — regex parser is cheaper, faster, deterministic
- **Float for money**
- **DDD refactor (#164)** — icebox
- **WireGuard / local LLM (#172)** — icebox

---

## Workflow — Every Implementation Task

```
Owner: "start issue #X"
  → [Project Manager] read project docs, verify alignment → ✅ or 🔴
  → [Tech Lead] create branch → delegate implementation
  → [Backend/Frontend Developer] implement task
  → Owner reviews in IDE
  → Owner: "OK" → create PR or owner does manually
  → Owner provides PR number → [Code Reviewer] review
```

### Branch naming
```bash
git checkout -b feat/<issue-number>-short-description
```

---

## GitHub-First Rule

**No implementation without a GitHub issue.**

1. Propose full title + body in console
2. Wait for owner approval
3. Create via `gh` CLI

### Issue format
```markdown
**Epic:** #<number> <Epic name>
**Priority:** P0 | P1 | P2

## Description
...

## Acceptance Criteria
- [ ] ...
```

Title prefixes: `[Backend]` / `[Frontend]` / `[Backend/Frontend]` / `Epic:`
Priorities: P0 = blocker, P1 = core value, P2 = important

---

## Project Documentation

All documentation is in `docs/` (gitignored — private):
- `docs/strategy/master-business-adr.md` — business decisions, model, roadmap, positioning
- `docs/decisions-log.md` — architectural and product decisions log

**Reference documents (read when needed):**
- `docs/RACHOWNIK_ARCHITEKTURA.md` — full OCR pipeline spec with code examples and component details
- `docs/RACHOWNIK_KONTEKST.md` — project and personal context, open-source launch strategy

Update docs after every conversation that changes priorities or architecture.

---

## Current State

- ✅ Working dashboard React + FastAPI
- ✅ Envelope budgeting, shared budget for couples
- ✅ Receipt staging area
- ⏳ **IN PROGRESS: OCR pipeline for receipts — MAIN BLOCKER**
- ❌ Forgot password
- ❌ PostgreSQL migration
- ❌ Merchant-specific parsers (Lidl, Biedronka)
- ❌ Bank CSV adapters

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
npm install
npm run dev       # http://localhost:5173
npm run build
npm run lint
```

### Database migrations (Alembic)
```bash
docker-compose exec backend alembic revision --autogenerate -m "description"
docker-compose exec backend alembic upgrade head
docker-compose exec backend alembic downgrade -1
```

### Production
```bash
cd frontend && npm run build
docker-compose -f docker-compose.prod.yml up --build -d
```

---

## Architecture

**Dev**: FastAPI in Docker (port 8000) + Vite (port 5173). Vite proxies `/api` → `localhost:8000`.
**Prod**: single container (`Dockerfile.vps`), port 8080.

### Stack
- **Backend**: FastAPI + SQLModel (Pydantic v2) + SQLite + Alembic
- **Frontend**: React 19 + Vite + TypeScript + TanStack Query + Shadcn/UI + Tailwind v4
- **Auth**: JWT (`python-jose`) + bcrypt — 7-day tokens
- **AI/OCR**: Google Vision DOCUMENT_TEXT_DETECTION + GPT-4o-mini, rapidfuzz for cache
- **Deploy**: Hetzner VPS, Docker

### Layered Architecture — TARGET (not fully implemented yet)

```
backend/app/api.py        ← FastAPI handlers, request/response validation
    ↓
backend/app/services/     ← Business logic  [currently: services.py single file]
    ↓
backend/app/repository/   ← Database access  [not yet extracted]
    ↓
backend/app/core/         ← OCR pipeline, parsers, AI calls  [not yet extracted]
```

Migrate toward this structure incrementally.

### Key files — Backend
- `backend/app/models.py` — SQLModel tables + Pydantic DTOs
- `backend/app/api.py` — all routes under `/api`
- `backend/app/services.py` — AIService (OpenAI)
- `backend/app/database.py` — engine, session dependency
- `backend/app/auth.py` — JWT, `get_current_user`

### Key files — Frontend
- `frontend/src/lib/api.ts` — Axios client + all API functions
- `frontend/src/types.ts` — shared TypeScript types
- `frontend/src/pages/` — page components
- `frontend/src/components/ui/` — Shadcn primitives (**never modify**)
- `frontend/src/context/AuthContext.tsx` — auth state

`@` alias → `frontend/src/`

### Auth flow
- `POST /api/auth/register`, `/login`, `GET /api/auth/me`
- All `/api/transactions` and `/api/budget` require Bearer token
- Axios interceptor adds token; 401 → clearAuth + redirect `/login`
- localStorage: `budget_token`, `budget_user`

---

## Tech Stack Notes

- **Zod v4**: `z.email()` not `z.string().email()` (deprecated)
- **bcrypt**: pin `>=3.0.0,<4.0.0` (v4 incompatible with passlib)
- **Shadcn/UI**: never modify `src/components/ui/`
- **Commits**: owner does manually — never auto-commit

---

## Environment

```env
OPENAI_API_KEY=your_api_key_here
GOOGLE_APPLICATION_CREDENTIALS=path/to/google-vision-credentials.json
ENVIRONMENT=development
SECRET_KEY=your_jwt_secret_here
```

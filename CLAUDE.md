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
- **Save important new details to memory during the session** — decisions, surprises, constraints, confirmed approaches worth remembering in future sessions

**Language**: Polish in all conversations with the owner. English in code and comments.

**Git commits**: Never add `Co-Authored-By` or any AI authorship attribution to commit messages — commits belong solely to the owner.

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

### Source-aware Adapter Strategy

Each input type has its own adapter. All produce the same `Receipt` (Unified Model).

```
[Source Detector & Router]
        ↓
┌───────┬──────────┬──────────┬──────────┐
↓       ↓          ↓          ↓          ↓
PDF    PDF        App PNG   Photo     Future:
text   image      (Lidl)    (camera)  e-Paragon
```

PNG from Lidl Plus is **easy** OCR (digital font, zero noise) — Google Vision accuracy ~99%. The problem is not OCR, it's structuring the output.

### Pipeline for Lidl Plus PNG (main use case)

```
PNG → Google Vision DOCUMENT_TEXT_DETECTION
    → Line reconstruction by bounding box geometry (sort Y, group, sort X)
    → Format Detector (merchant signature regex)
    → Lidl Deterministic Parser (state machine + regex)
    → Validation (sum of items == receipt total)
    → Cache lookup (rapidfuzz, threshold 85%)
    → AI categorization ONLY for new products (GPT-4o-mini, batch, structured output)
    → Staging area (user accepts/edits only categories)
    → Persist
```

**Realistic timing after rollout:** <3s for 60-item receipt, <1.5s after 3 months when cache covers 70%+.

---

## Critical Implementation Rules

### Chunking — ALWAYS text, NEVER image

**DO NOT chunk images** — causes hallucinations and duplicate items. Instead:
- Whole receipt → single OCR call
- Text after OCR → segmentation into product blocks (deterministic, regex-based)
- Blocks → chunks of 10-15 items → parallel to AI (`asyncio.gather`)

### Sum validation is mandatory

Every receipt MUST validate: `sum(items.total_after_discount) == receipt.total` (tolerance ±0.01 PLN). This is the **only real defense** against AI hallucinations and parser errors. All competing projects in receipt OCR space skip this — it's our quality differentiator.

### Cache-first for categorization

Before any AI call: fuzzy lookup (rapidfuzz, threshold 85%) in user's product cache. AI is used ONLY for unknown items. After categorization, save to cache. Expected hit rate: 50% after a month, 80%+ after 3 months.

### Status enum for extract jobs

Every job progresses through: `QUEUED → RUNNING → OCR_OK → PARSING_OK → CATEGORIZATION_OK | NEEDS_REVIEW | FAILED`. Per-stage tracking helps debugging and UI feedback.

### SHA256 deduplication

`receipt_files` table with unique constraint on `(user_id, content_hash)`. Re-uploading same file = no-op instead of duplicate.

### Worker pool for OCR

OCR and AI processing must NOT block the upload endpoint. Enqueue to channel, worker pool processes asynchronously. Stream status to frontend via WebSocket/SSE.

### Money handling

**Decimal arithmetic** for all monetary amounts (NEVER float). Pydantic models for all data structures flowing through the pipeline.

---

## What to AVOID

- **Image chunking** — causes duplicates, don't do it
- **GPT-4 Vision with 512x512 tiling** — loses coherence on long receipts
- **Flat text concatenation from Vision** — loses column structure, use line reconstruction
- **AI for structuring known formats** — regex parser is cheaper, faster, deterministic
- **Hardcoded universal categories** — categories are Polish and family-specific, not US tax categories
- **Float for money**
- **DDD refactor (#164)** — over-engineering without users, in icebox
- **WireGuard / local LLM (#172)** — icebox, not now

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

All documentation is in `docs/` (gitignored — private):
- `docs/strategy/master-business-adr.md` — business decisions, model, roadmap, positioning
- `docs/decisions-log.md` — architectural and product decisions log

**Reference documents (read when needed for deeper context):**
- `docs/RACHOWNIK_ARCHITEKTURA.md` — full OCR pipeline spec with code examples and component details
- `docs/reference-repositories.md` — analysed reference repos with priorities and what to learn from each
- `docs/RACHOWNIK_KONTEKST.md` — project and personal context, open-source launch strategy

**Update docs after every conversation that changes priorities, architecture, or product direction.**

---

## Current State (update after each session)

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
pnpm install       # Install dependencies
pnpm dev       # Dev server at http://localhost:5173
pnpm build     # Production build
pnpm lint      # ESLint
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
cd frontend && pnpm build
docker-compose -f docker-compose.prod.yml up --build -d
```

### Debug CLIs (planned — implement as part of OCR pipeline)

Each pipeline stage should be available as separate CLI for debugging:
```bash
python -m rachownik.cli.ocr <file>              # OCR only, output: text + bounding boxes JSON
python -m rachownik.cli.reconstruct <ocr_json>  # Line reconstruction from OCR output
python -m rachownik.cli.parse-lidl <text>       # Lidl parser only, output: structured JSON
python -m rachownik.cli.categorize <products>   # Categorization only
python -m rachownik.cli.full-pipeline <file>    # Full end-to-end pipeline
```

Invaluable during development, perfect for bug reports (user sends file, we run locally).

---

## Architecture (Implementation Detail)

**Dev**: two services — FastAPI in Docker (port 8000) + Vite dev server (port 5173). Vite proxies `/api` to `localhost:8000`.

**Prod**: single container (`Dockerfile.vps`) — FastAPI serves React build as static files on port 8080.

### Stack
- **Backend**: FastAPI + SQLModel (Pydantic v2) + SQLite + Alembic
- **Frontend**: React 19 + Vite + TypeScript + TanStack Query + Shadcn/UI + Tailwind v4
- **Auth**: JWT (`python-jose`) + bcrypt (`passlib`) — 7-day tokens
- **AI/OCR**: Google Vision DOCUMENT_TEXT_DETECTION + GPT-4o-mini, rapidfuzz for cache
- **Deploy**: Hetzner VPS, Docker

### Layered Architecture — TARGET (not fully implemented yet)

Inspired by joseph-ayodele/receipts-tracker reference project:

```
backend/app/api.py        ← FastAPI handlers, request/response validation
    ↓
backend/app/services/     ← Business logic, orchestration  [currently: services.py single file]
    ↓
backend/app/repository/   ← Database access, returns domain types  [not yet extracted]
    ↓
backend/app/core/         ← OCR pipeline, parsers, AI calls  [not yet extracted]
```

Dependencies flow in one direction only. Migrate toward this structure incrementally — don't refactor all at once.

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
GOOGLE_APPLICATION_CREDENTIALS=path/to/google-vision-credentials.json
ENVIRONMENT=development
SECRET_KEY=your_jwt_secret_here
```
``

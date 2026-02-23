# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

### Backend
```bash
# Start backend with hot reload (API only, development)
docker-compose up --build -d

# View logs
docker-compose logs -f

# Stop backend
docker-compose down
```

### Frontend
```bash
cd frontend
npm install       # Install dependencies
npm run dev       # Start dev server at http://localhost:5173
npm run build     # Build for production (outputs to frontend/dist)
npm run lint      # Run ESLint
npm run preview   # Preview production build locally
```

### Production Deployment (VPS)
```bash
# 1. Build frontend locally first (avoids RAM usage on server)
cd frontend && npm run build

# 2. Transfer project to server, then on server:
docker-compose -f docker-compose.prod.yml up --build -d
```

## Environment Setup

Create `.env` in the project root:
```env
OPENAI_API_KEY=your_api_key_here
ENVIRONMENT=development
```

## Architecture

**Two-service architecture** during development, single container in production:

- **Backend**: FastAPI (Python) running in Docker on port `8000`. Uses SQLModel ORM with SQLite. Database file persists in `./data/`.
- **Frontend**: React 19 SPA running locally via Vite dev server on port `5173`. Vite proxies all `/api` requests to `localhost:8000`.
- **Production**: A single Docker container (`Dockerfile.vps`) serves both — FastAPI serves the React build from its `static/` directory and exposes port `8080`.

### Backend Data Flow

1. `POST /api/upload` receives an image file, computes SHA256 hash for duplicate detection, saves file to `static/uploads/`, creates a `Receipt` record with `status="processing"`, and dispatches `process_receipt_in_background` as a FastAPI `BackgroundTask`.
2. The background task calls `AIService.parse_receipt()` (GPT-4o-mini via OpenAI vision API), updates the receipt with extracted fields, creates `Item` records, sets `status="done"`, and deletes the image file.
3. On failure, sets `status="error"` (image is preserved so the user can retry via `POST /api/receipts/{id}/retry`).

### Receipt Status Lifecycle
`processing` → `done` | `error`

### Key Backend Files
- `backend/app/models.py` — SQLModel table definitions (`Receipt`, `Item`, `Budget`) and Pydantic DTOs
- `backend/app/api.py` — All API routes under `/api` prefix
- `backend/app/services.py` — `AIService.parse_receipt()`: encodes image to base64, calls OpenAI, returns parsed JSON
- `backend/app/database.py` — SQLite engine and session dependency

### Frontend Structure
- `src/lib/api.ts` — Axios client (baseURL `/api`) with all API call functions
- `src/types.ts` — TypeScript types shared across components
- `src/pages/Dashboard.tsx` — Single page that composes all dashboard components
- `src/components/dashboard/` — Feature components (UploadBox, ReceiptsTable, SpendingChart, etc.)
- `src/components/ui/` — Shadcn/UI primitive components (do not modify)
- `src/lib/constants.ts` — Shared constants (categories, etc.)

The `@` path alias maps to `frontend/src/`.

### State Management
TanStack Query manages all server state. `useQuery` fetches receipts and budget; `useMutation` handles uploads, updates, and deletes with cache invalidation.

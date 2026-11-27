# Production Deployment Guide

## Architecture Targets

- **Frontend**: Vercel (Static + Edge CDN)
- **Backend**: Render Python Web Service (FastAPI + Uvicorn + Alembic)
- **Primary Database**: Managed PostgreSQL 16 (Render Postgres, Neon, or Supabase)
- **Cache / Event Bus**: Managed Redis 7 (Render Key Value / Upstash Redis)

---

## 1. Local Docker Compose Deployment

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Launch PostgreSQL 16, Redis 7, FastAPI Backend (with automatic `alembic upgrade head`), and Nginx Frontend:
   ```bash
   docker compose up --build
   ```
3. Open `http://localhost:3000` (Frontend) and `http://localhost:8000/docs` (Backend OpenAPI).

---

## 2. Backend + Managed PostgreSQL + Managed Redis on Render

1. Push the repository to GitHub/GitLab.
2. In the **Render Dashboard**, select **New + → Blueprint** and connect the repository (`render.yaml` is pre-configured at the root).
3. Render automatically provisions:
   - `llmcc-postgres` (Managed PostgreSQL)
   - `llmcc-redis` (Managed Redis)
   - `llm-control-center-api` (Python Web Service executing `pip install -r requirements.txt && alembic upgrade head` on build and health-checked via `/health`)
4. Set `CORS_ALLOWED_ORIGINS` in the Render service environment variables to your Vercel production domain (e.g., `https://llm-control-center.vercel.app`).
5. *(Optional)* Configure server-wide fallback keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`) in Render Secret Environment Variables, or connect keys per user directly inside the UI's encrypted Providers vault.

---

## 3. Frontend Deployment on Vercel

1. In the **Vercel Dashboard**, click **Add New → Project** and import the repository.
2. Configure **Root Directory** to `frontend`.
3. Framework Preset: **Vite** (`npm run build`, output directory `dist`).
4. Set the single public environment variable (NEVER place any LLM API keys in Vercel):
   ```
   VITE_API_BASE_URL=https://llm-control-center-api.onrender.com
   ```
5. Deploy. `frontend/vercel.json` automatically configures SPA routing and strict security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`).

---

## 4. Post-Deployment Verification Checklist

1. Verify `GET https://<backend-domain>/ready` returns `200 OK` with `"database": {"status": "operational", "dialect": "postgresql"}` and `"redis": {"status": "operational"}`.
2. Register an operator account on the Vercel URL.
3. Navigate to **Providers**, connect at least one official API key (OpenAI, Google Gemini, or Anthropic Claude), and verify live status transitions to **Operational / Verified**.
4. Open **AI Chat**, stream a multi-turn conversation, switch models mid-conversation, refresh the browser to confirm PostgreSQL persistence, and verify real-time updates on **Overview**, **Live Monitoring**, **Analytics**, and **API Logs**.

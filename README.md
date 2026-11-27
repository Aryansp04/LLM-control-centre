# LLM Control Center

A production-ready multi-provider AI chat, live SSE streaming, real-time infrastructure & model availability monitoring, and API telemetry analytics platform integrating **OpenAI**, **Google Gemini**, and **Anthropic Claude** via their official APIs.

---

## Key Capabilities

- **Multi-Provider LLM Engine**: Unified async adapter registry (`OpenAIAdapter`, `GeminiAdapter`, `AnthropicAdapter`) with capability detection (e.g., fixed-temperature reasoning models vs configurable chat models, vision support, per-provider temperature clamping), exponential backoff with jitter on transient errors, and mid-generation cancellation.
- **Advanced AI Chat**: Real-time token streaming via **Server-Sent Events (SSE)**, mid-conversation model switching with context preservation, token-budget context window manager, Markdown + syntax-highlighted code blocks, conversation search/rename/delete/export (Markdown & JSON), regenerate/retry, and validated file attachments (`.txt`, `.md`, `.csv`, `.json`, `.py`, `.pdf`, `.png`, `.jpg`, `.webp`, `.gif`).
- **Four-Tier Real-Time Monitoring**: Strictly separates (1) Application Health (Backend, PostgreSQL/DB, Redis, Streaming sockets), (2) Provider API Reachability, (3) API-Account Credential Status, and (4) Model-Specific Endpoint Availability (including optional 1-token deep inference probes).
- **Live Event Bus**: Authenticated, per-user isolated **WebSocket** (`/ws/events`) with heartbeats and sequence-numbered reconnection replay.
- **Versioned Cost & Usage Analytics**: Daily, weekly, and monthly summaries, date/provider/model/status filters, latency & TTFT & tokens/sec metrics, and transparent estimated cost calculations using versioned per-model list rates.
- **Security**: `bcrypt` password hashing, revocable JWTs backed by Redis, **Fernet (AES-128-CBC + HMAC-SHA256)** encryption at rest for provider API keys, sliding-window rate limiting, strict HTTP security headers, and automated secret log redaction.

---

## Quick Start (Docker Compose — Full PostgreSQL 16 + Redis 7)

```bash
cp .env.example .env
docker compose up --build
```
- **Frontend**: `http://localhost:3000`
- **Backend API & Docs**: `http://localhost:8000/docs`

---

## Quick Start (Standalone Local Mode — No Docker Required)

1. **Backend**:
   ```powershell
   cd backend
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements.txt
   .\.venv\Scripts\alembic upgrade head
   .\.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
2. **Frontend**:
   ```powershell
   cd frontend
   npm install
   npm run dev
   ```
   Open `http://127.0.0.1:5173`.

---

## Running Automated Tests

### Backend Unit & Resilience Suite (Mocked Providers)
```powershell
cd backend
.\.venv\Scripts\pytest -v
```

### Live Upstream Provider Integration Tests (Real API Credentials)
```powershell
cd backend
$env:RUN_LIVE_PROVIDER_TESTS="1"
$env:OPENAI_API_KEY="sk-..."      # and/or GEMINI_API_KEY / ANTHROPIC_API_KEY
.\.venv\Scripts\pytest -v -m live_provider
```

### Frontend Test Suite & TypeScript Production Build
```powershell
cd frontend
npm run test
npm run build
```

See [ARCHITECTURE.md](./ARCHITECTURE.md), [API_DOCUMENTATION.md](./API_DOCUMENTATION.md), and [DEPLOYMENT.md](./DEPLOYMENT.md) for complete reference details.

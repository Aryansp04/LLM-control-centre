# LLM Control Center — System Architecture

## 1. Architectural Overview

**LLM Control Center** is a multi-tenant, user-isolated AI operations and conversational platform integrating official LLM APIs (**OpenAI**, **Google Gemini**, and **Anthropic Claude**) through a unified asynchronous provider engine, paired with real-time health telemetry, token/cost accounting, Server-Sent Events (SSE) token streaming, and authenticated WebSocket live dashboards.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         React + TypeScript Frontend                          │
│  Overview │ AI Chat (SSE) │ Models │ Providers │ Live Monitoring (WS)        │
│  Analytics │ API Logs │ Settings (Encrypted Key Vault)                       │
└───────────────────┬──────────────────────────────────────┬───────────────────┘
                    │ HTTPS REST + SSE (/api/chat/stream)  │ WSS (/ws/events)
                    ▼                                      ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Asynchronous Backend                          │
│  ┌─────────────────┐  ┌──────────────────────┐  ┌─────────────────────────┐  │
│  │ Security Layer  │  │ Multi-Provider Engine│  │ Live Event Bus & WS Hub │  │
│  │ JWT + Refresh   │  │ Registry + Adapters  │  │ Per-User Isolation      │  │
│  │ Fernet Vault    │  │ Retry + Cancellation │  │ Heartbeats & Recovery   │  │
│  │ Rate Limiter    │  │ Context Window Mgmt  │  │ SSE Stream Coordinator  │  │
│  └────────┬────────┘  └──────────┬───────────┘  └────────────┬────────────┘  │
│           │                      │                           │               │
│  ┌────────▼──────────────────────▼───────────────────────────▼────────────┐  │
│  │        Monitoring Engine & Versioned Pricing Analytics Service         │  │
│  │  Provider/Account/Model Probe Separation │ TTFT & TPS Telemetry        │  │
│  └───────────────────────┬───────────────────────────────┬────────────────┘  │
└──────────────────────────┼───────────────────────────────┼───────────────────┘
                           ▼                               ▼
           ┌───────────────────────────────┐ ┌───────────────────────────┐
           │          PostgreSQL           │ │           Redis           │
           │ 10 Normalized Entities        │ │ Rate Limiting (Sliding)   │
           │ Alembic Migrations & Indexes  │ │ Ephemeral Session/Cancel  │
           │ Strict user_id Isolation      │ │ Pub/Sub Live Event Bus    │
           └───────────────────────────────┘ │ Health/Telemetry Cache    │
                                             └───────────────────────────┘
```

## 2. Repository Structure

```
llm-control-center/
├── ARCHITECTURE.md
├── README.md
├── DEPLOYMENT.md
├── API_DOCUMENTATION.md
├── docker-compose.yml
├── .env.example
├── render.yaml
├── backend/
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── migrations/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/
│   │       └── 0001_initial_schema.py
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── redis_client.py
│   │   ├── models/              # 10 PostgreSQL SQLAlchemy 2.0 entities
│   │   ├── schemas/             # Pydantic v2 request/response schemas
│   │   ├── core/                # Auth, encryption, rate limit, errors, logging
│   │   ├── providers/           # Registry + BaseAdapter + OpenAI/Gemini/Anthropic
│   │   ├── services/            # Chat, context manager, attachments, pricing, monitoring, analytics, events
│   │   └── api/                 # REST routers + authenticated WebSocket endpoint
│   └── tests/                   # Isolated unit + integration + live provider tests
└── frontend/
    ├── Dockerfile
    ├── vercel.json
    ├── package.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── api/                 # Typed REST, SSE stream client, reconnecting WS client
        ├── context/             # Auth, Workspace/Active Model, Live Telemetry store
        ├── components/          # Layout shell, Sidebar, Topbar, Charts, Markdown/Code, Skeletons
        ├── pages/               # Overview, Chat, Models, Providers, Monitoring, Analytics, Logs, Settings
        └── test/                # Vitest + Testing Library automated UI tests
```

## 3. Core Engineering Decisions

1. **Unified Provider Abstraction & Capability Detection (`app/providers/`)**:
   - Each provider adapter (`OpenAIAdapter`, `GeminiAdapter`, `AnthropicAdapter`) declares explicit `ModelCapabilities` (`supports_streaming`, `supports_system_instruction`, `supports_temperature`, `supports_max_tokens`, `supports_vision`, `supports_files`, `context_window`, `max_output_tokens`).
   - Uses official HTTP APIs via `httpx.AsyncClient` / official SDK protocols with granular timeout controls, cancellation tokens (`asyncio.Event` + Redis cross-worker cancel signal), and exponential backoff with jitter ONLY on transient errors (`429`, `500`, `502`, `503`, `504`, network timeouts), never retrying `400`/`401`/`403`.
   - Captures monotonic high-resolution timestamps for total latency, **Time to First Token (TTFT)**, **Tokens Per Second (TPS)**, exact provider model string returned in the payload, and provider-reported prompt/completion token counts (with deterministic tokenizer fallback if a stream aborts mid-flight).

2. **Four-Tier Health Separation (`app/services/monitoring.py`)**:
   - **Application Health**: FastAPI process, PostgreSQL query roundtrip latency, Redis PING roundtrip latency, active SSE/WS stream state.
   - **Provider-Wide / Endpoint Reachability**: Transport-level & auth-handshake probe.
   - **API-Account Access**: Credential validity & quota/rate-limit verification (`configured`, `reachable`, `rate_limited`, `unauthorized`).
   - **Model-Specific Availability**: Optional lightweight 1-token inference probe (`POST /api/monitoring/check` with `deep_model_probe=true`) proving the exact model endpoint can generate tokens, never conflating marketing site uptime or `/models` listing with model generation availability.

3. **Security & Secret Isolation (`app/core/security.py`)**:
   - Passwords hashed with `bcrypt`.
   - JWT access tokens + HTTP-only / revocable session jti tracked in Redis.
   - User-supplied provider API keys encrypted at rest with **AES-128-CBC + HMAC-SHA256 (Fernet)** derived via HKDF from `ENCRYPTION_SECRET_KEY`. Keys are masked (`sk-...abcd`) in any metadata response and stripped from logs via a structured log redaction filter.

4. **Database Entities (10 Tables)**:
   1. `users`
   2. `providers` (per-user encrypted credentials & status + system defaults)
   3. `models` (capabilities, context window, versioned pricing metadata, status)
   4. `conversations` (user-isolated threads, active provider/model, pinned system prompt, token totals)
   5. `messages` (role, content, attachments metadata, actual model used, tokens, latency, TTFT, finish status)
   6. `api_requests` (every chat & probe call with request_id, HTTP status, latency_ms, ttft_ms, tokens_per_sec, error codes, estimated_cost_usd)
   7. `model_health_checks` (provider status, model status, probe type, latency_ms, diagnostic error)
   8. `usage_records` (granular per-request ledger with pricing_version, input/output unit rates, estimated_cost_usd)
   9. `monitoring_events` (persisted real-time operational events isolated by user)
   10. `user_settings` (default provider/model, temperature, max_tokens, theme/telemetry preferences)

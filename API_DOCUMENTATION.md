# LLM Control Center — API Documentation

Interactive OpenAPI / Swagger documentation is automatically served by the backend at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

All `/api/*` endpoints (except `/api/auth/register` and `/api/auth/login`) require:
```
Authorization: Bearer <access_token>
```
Every HTTP response includes `X-Request-ID` for end-to-end correlation, and all errors follow a uniform envelope:
```json
{
  "error": {
    "code": "error_code",
    "message": "Human-readable sanitized description",
    "details": {},
    "request_id": "req_0192abcd..."
  }
}
```

---

## 1. Authentication

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/register` | Register user, initialize providers/models/settings, issue JWT |
| `POST` | `/api/auth/login` | Authenticate email + password, issue JWT |
| `POST` | `/api/auth/logout` | Revoke active JWT `jti` in Redis |
| `GET` | `/api/auth/me` | Return authenticated user profile |

---

## 2. Providers & Models

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/providers` | List providers with masked `key_hint`, `status`, `account_status`, and capabilities |
| `PUT` | `/api/providers/{provider_key}` | Encrypt & store API key (Fernet), clear key, or update base URL / org ID |
| `GET` | `/api/models` | List models with capabilities, context window, and versioned pricing (`?provider_key=`) |
| `POST` | `/api/models` | Register an additional model ID under an existing provider |
| `GET` | `/api/models/{model_id}` | Fetch detailed model specification and status |

---

## 3. Chat, SSE Streaming & Conversations

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat/completions` | Non-streaming completion with context window budgeting & telemetry |
| `POST` | `/api/chat/stream` | **Server-Sent Events (`text/event-stream`)** streaming tokens (`stream_start`, `token`, `stream_end`, `cancelled`, `error`) |
| `POST` | `/api/chat/cancel` | Cancel an active streaming generation (`{"stream_id": "..."}`) |
| `POST` | `/api/chat/attachments/validate` | Multipart file validation & extraction (`.txt`, `.md`, `.csv`, `.json`, `.py`, `.pdf`, `.png`, `.jpg`, `.webp`, `.gif`) |
| `GET` | `/api/conversations` | Paginated conversation list with full-text `search` across titles & messages |
| `POST` | `/api/conversations` | Create a new conversation |
| `GET` | `/api/conversations/{id}` | Retrieve conversation metadata and ordered messages |
| `PATCH` | `/api/conversations/{id}` | Rename conversation, pin/unpin, or switch active provider/model |
| `DELETE` | `/api/conversations/{id}` | Delete conversation and cascade messages |
| `GET` | `/api/conversations/{id}/export` | Export conversation in `markdown` or `json` format (`?format=markdown`) |

---

## 4. Real-Time Monitoring & Live WebSockets

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/monitoring/overview` | 8 live dashboard cards, 4-component app status, provider/model table, recent events |
| `GET` | `/api/monitoring/providers` | Provider reachability, account status, error %, and latency |
| `GET` | `/api/monitoring/models` | Independent per-model status, TTFT, tokens/sec, and error rates |
| `GET` | `/api/monitoring/history` | Historical `ModelHealthCheck` records |
| `POST` | `/api/monitoring/check` | Execute on-demand provider & model probes (`{"provider_key": null, "deep_inference": false}`) |
| `POST` | `/api/monitoring/events/read-all` | Mark monitoring notification events as read |
| `WS` | `/ws/events?token=<jwt>&last_seq=0` | Authenticated per-user WebSocket emitting heartbeats, status transitions, and live telemetry |

---

## 5. Analytics, API Logs, Settings & Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/analytics/usage` | Daily/weekly/monthly summaries + filtered time-series (`granularity`, `start_date`, `end_date`, `provider`, `model`, `status`) |
| `GET` | `/api/analytics/tokens` | Input vs output token consumption time-series |
| `GET` | `/api/analytics/latency` | Average & P95 latency, TTFT, and tokens/sec |
| `GET` | `/api/analytics/cost` | Versioned estimated cost breakdown with explicit estimation metadata |
| `GET` | `/api/logs` | Paginated `APIRequest` audit log |
| `GET` / `PUT` | `/api/settings` | Read or update workspace settings |
| `GET` | `/health` | Process liveness probe (`200 OK`) |
| `GET` | `/ready` | Dependency readiness probe verifying Database & Redis (`200 OK` or `503 Service Unavailable`) |

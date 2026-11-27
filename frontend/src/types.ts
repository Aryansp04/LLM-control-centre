export interface User {
  id: string;
  email: string;
  username: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface ProviderQuota {
  window_hours: number;
  token_limit: number;
  used_tokens: number;
  remaining_tokens: number;
  remaining_pct: number;
  used_pct: number;
  next_recovery_at: string;
  resets_to_100_at: string;
  reset_in_seconds: number;
}

export interface ProviderInfo {
  id: string;
  provider_key: string;
  display_name: string;
  has_api_key: boolean;
  credential_source: "user_vault" | "server_env" | "none";
  key_hint: string | null;
  base_url_override: string | null;
  organization_id: string | null;
  is_enabled: boolean;
  status: "operational" | "degraded" | "unavailable" | "unknown";
  account_status:
    | "unconfigured"
    | "configured"
    | "verified"
    | "invalid_credentials"
    | "rate_limited"
    | "quota_exceeded";
  last_checked_at: string | null;
  last_latency_ms: number | null;
  last_error: string | null;
  capabilities: Record<string, unknown>;
  model_count: number;
  quota?: ProviderQuota | null;
}

export interface ModelInfo {
  id: string;
  provider_id: string;
  provider_key: string;
  provider_name: string;
  model_id: string;
  display_name: string;
  description: string | null;
  context_window: number;
  max_output_tokens: number;
  supports_streaming: boolean;
  supports_system_instruction: boolean;
  supports_temperature: boolean;
  supports_max_tokens: boolean;
  supports_vision: boolean;
  supports_file_attachments: boolean;
  input_price_per_1m: number | null;
  output_price_per_1m: number | null;
  pricing_version: string;
  status:
    | "unconfigured"
    | "configured"
    | "reachable"
    | "request_successful"
    | "request_failed"
    | "rate_limited";
  provider_status: string;
  account_status: string;
  has_credentials: boolean;
  is_available: boolean;
  last_checked_at: string | null;
  last_latency_ms: number | null;
  last_error: string | null;
}

export interface AttachmentMeta {
  filename: string;
  mime_type: string;
  size_bytes: number;
  kind: "text" | "image" | "pdf";
  base64_content?: string;
  preview_url?: string | null;
  extracted_preview?: string | null;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  provider_key: string | null;
  requested_model: string | null;
  actual_model_used: string | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  latency_ms: number | null;
  ttft_ms: number | null;
  tokens_per_second: number | null;
  estimated_cost_usd: number | null;
  status: "streaming" | "completed" | "cancelled" | "failed";
  error_message: string | null;
  attachments: AttachmentMeta[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  active_provider: string;
  active_model: string;
  system_instruction: string | null;
  temperature: number | null;
  max_output_tokens: number | null;
  total_input_tokens: number;
  total_output_tokens: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  message_count: number;
  is_pinned: boolean;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
}

export interface MonitoringOverview {
  cards: {
    total_providers: number;
    configured_providers: number;
    operational_providers: number;
    available_models: number;
    total_models: number;
    active_generations: number;
    total_requests: number;
    successful_requests: number;
    failed_requests: number;
    avg_latency_ms: number | null;
    avg_ttft_ms: number | null;
    avg_tokens_per_second: number | null;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    error_rate_pct: number;
    estimated_cost_usd: number;
  };
  application_status: {
    backend: { status: string; healthy: boolean; uptime_seconds: number };
    database: {
      status: string;
      healthy: boolean;
      dialect: string;
      latency_ms: number;
      error: string | null;
    };
    redis: {
      status: string;
      healthy: boolean;
      mode: string;
      latency_ms: number;
      error: string | null;
    };
    streaming: {
      status: string;
      healthy: boolean;
      active_websocket_connections: number;
      active_sse_generations: number;
    };
  };
  provider_status_table: Array<{
    model_db_id: string;
    provider_key: string;
    provider_name: string;
    provider_status: string;
    account_status: string;
    has_credentials: boolean;
    model_id: string;
    model_name: string;
    model_status: string;
    latency_ms: number | null;
    last_checked_at: string | null;
    last_error: string | null;
  }>;
  recent_events: LiveEvent[];
}

export interface LiveEvent {
  id: string;
  seq?: number;
  type: string;
  severity: "info" | "warning" | "error" | "critical";
  provider_key: string | null;
  model_id: string | null;
  title: string;
  message: string;
  payload: Record<string, unknown>;
  is_read?: boolean;
  timestamp: string;
}

export interface AnalyticsReport {
  summary: {
    total_requests: number;
    successful_requests: number;
    failed_requests: number;
    cancelled_requests: number;
    failure_rate_pct: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number | null;
    p95_latency_ms: number | null;
    avg_ttft_ms: number | null;
    avg_tokens_per_second: number | null;
    estimated_cost_usd: number;
    is_cost_estimated: boolean;
    pricing_version: string;
    priced_requests: number;
    unpriced_requests: number;
  };
  periods: {
    daily: { requests: number; tokens: number; estimated_cost_usd: number; failed: number };
    weekly: { requests: number; tokens: number; estimated_cost_usd: number; failed: number };
    monthly: { requests: number; tokens: number; estimated_cost_usd: number; failed: number };
  };
  timeseries: Array<{
    bucket: string;
    requests: number;
    successful: number;
    failed: number;
    cancelled: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number;
    avg_ttft_ms: number | null;
    estimated_cost_usd: number;
  }>;
  by_provider: Array<{
    provider_key: string;
    requests: number;
    successful: number;
    failed: number;
    failure_rate_pct: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number;
    estimated_cost_usd: number;
  }>;
  by_model: Array<{
    provider_key: string;
    model_id: string;
    requests: number;
    successful: number;
    failed: number;
    failure_rate_pct: number;
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    avg_latency_ms: number;
    avg_ttft_ms: number | null;
    avg_tokens_per_second: number | null;
    estimated_cost_usd: number;
    pricing_version: string;
  }>;
}

export interface WorkspaceSettings {
  workspace_name: string;
  default_provider: string;
  default_model: string;
  default_temperature: number;
  default_max_tokens: number;
  default_system_instruction: string | null;
  context_max_tokens_ratio: number;
  auto_monitoring_enabled: boolean;
  monitoring_interval_seconds: number;
  enable_deep_model_probe: boolean;
  notifications_enabled: boolean;
  updated_at: string;
}

export interface ApiLogEntry {
  id: string;
  request_id: string;
  conversation_id: string | null;
  provider_key: string;
  requested_model: string;
  actual_model_used: string | null;
  endpoint_type: string;
  is_streaming: boolean;
  status: string;
  http_status_code: number | null;
  error_type: string | null;
  error_message: string | null;
  retry_count: number;
  latency_ms: number;
  ttft_ms: number | null;
  tokens_per_second: number | null;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  pricing_version: string | null;
  created_at: string;
}

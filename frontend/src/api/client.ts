import { LiveEvent } from "../types";

const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) || "";
export const API_BASE_URL = RAW_BASE.replace(/\/$/, "");

const TOKEN_STORAGE_KEY = "llmcc_access_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredToken(token: string | null): void {
  if (token) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  }
}

let unauthorizedCallback: (() => void) | null = null;
export function onUnauthorized(cb: () => void): void {
  unauthorizedCallback = cb;
}

export class ApiClientError extends Error {
  code: string;
  status: number;
  requestId?: string;

  constructor(message: string, code = "api_error", status = 400, requestId?: string) {
    super(message);
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (!(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  if (response.status === 401 && !path.startsWith("/api/auth/login")) {
    unauthorizedCallback?.();
  }

  const contentType = response.headers.get("content-type") || "";
  if (!response.ok) {
    if (contentType.includes("application/json")) {
      const errJson = await response.json();
      const errObj = errJson?.error || {};
      throw new ApiClientError(
        errObj.message || `Request failed (${response.status})`,
        errObj.code || `http_${response.status}`,
        response.status,
        errObj.request_id
      );
    }
    const text = await response.text();
    throw new ApiClientError(
      text || `Request failed (${response.status})`,
      `http_${response.status}`,
      response.status
    );
  }

  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }
  return (await response.text()) as unknown as T;
}

export interface StreamHandlers {
  onStart?: (data: {
    stream_id: string;
    request_id: string;
    conversation_id: string;
    conversation_title: string;
    user_message_id: string;
    assistant_message_id: string;
    provider_key: string;
    requested_model: string;
    omitted_context_messages: number;
  }) => void;
  onToken?: (delta: string, actualModel?: string) => void;
  onEnd?: (telemetry: Record<string, unknown>) => void;
  onCancelled?: (telemetry: Record<string, unknown>) => void;
  onError?: (err: { code: string; message: string; telemetry?: Record<string, unknown> }) => void;
}

export async function streamChatCompletion(
  payload: Record<string, unknown>,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  const token = getStoredToken();
  const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok || !response.body) {
    let message = `Streaming request failed (${response.status})`;
    let code = `http_${response.status}`;
    try {
      const errBody = await response.json();
      message = errBody?.error?.message || message;
      code = errBody?.error?.code || code;
    } catch {
      // ignore parse fallback
    }
    throw new ApiClientError(message, code, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundaryIndex = buffer.indexOf("\n\n");
    while (boundaryIndex !== -1) {
      const rawFrame = buffer.slice(0, boundaryIndex);
      buffer = buffer.slice(boundaryIndex + 2);

      let eventType = "message";
      const dataLines: string[] = [];
      for (const line of rawFrame.split("\n")) {
        const trimmed = line.trim();
        if (trimmed.startsWith("event:")) {
          eventType = trimmed.slice(6).trim();
        } else if (trimmed.startsWith("data:")) {
          dataLines.push(trimmed.slice(5).trim());
        }
      }

      if (dataLines.length > 0) {
        const parsed = JSON.parse(dataLines.join("\n"));
        if (eventType === "stream_start") {
          handlers.onStart?.(parsed);
        } else if (eventType === "token") {
          handlers.onToken?.(parsed.delta || "", parsed.actual_model);
        } else if (eventType === "stream_end") {
          handlers.onEnd?.(parsed);
        } else if (eventType === "cancelled") {
          handlers.onCancelled?.(parsed);
        } else if (eventType === "error") {
          handlers.onError?.(parsed);
        }
      }

      boundaryIndex = buffer.indexOf("\n\n");
    }
  }
}

export type WsConnectionState =
  | "connected"
  | "connecting"
  | "reconnecting"
  | "disconnected";

export class LiveTelemetrySocket {
  private ws: WebSocket | null = null;
  private lastSeq = 0;
  private reconnectTimer: number | null = null;
  private pingTimer: number | null = null;
  private fallbackPollTimer: number | null = null;
  private reconnectAttempts = 0;
  private manualClose = false;
  private onEvent: (ev: LiveEvent) => void;
  private onStateChange: (state: WsConnectionState) => void;
  private onFallbackPoll?: () => void;

  constructor(
    onEvent: (ev: LiveEvent) => void,
    onStateChange: (state: WsConnectionState) => void,
    onFallbackPoll?: () => void
  ) {
    this.onEvent = onEvent;
    this.onStateChange = onStateChange;
    this.onFallbackPoll = onFallbackPoll;
  }

  connect(): void {
    const token = getStoredToken();
    if (!token) {
      this.onStateChange("disconnected");
      return;
    }
    this.manualClose = false;
    this.onStateChange(this.reconnectAttempts > 0 ? "reconnecting" : "connecting");

    let wsOrigin: string;
    if (API_BASE_URL) {
      wsOrigin = API_BASE_URL.replace(/^http/, "ws");
    } else {
      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      wsOrigin = `${proto}//${window.location.host}`;
    }

    const url = `${wsOrigin}/ws/events?token=${encodeURIComponent(token)}&last_seq=${this.lastSeq}`;
    try {
      this.ws = new WebSocket(url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.onStateChange("connected");
      this.startHeartbeat();
    };

    this.ws.onmessage = (msgEvent) => {
      try {
        const data = JSON.parse(msgEvent.data);
        if (typeof data.seq === "number" && data.seq > this.lastSeq) {
          this.lastSeq = data.seq;
        }
        if (
          data.type === "connection_ready" ||
          data.type === "heartbeat" ||
          data.type === "pong"
        ) {
          return;
        }
        this.onEvent(data as LiveEvent);
      } catch {
        // ignore malformed frames
      }
    };

    this.ws.onclose = (ev) => {
      this.stopHeartbeat();
      if (this.manualClose || ev.code === 1008) {
        this.onStateChange("disconnected");
        return;
      }
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.pingTimer = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "ping", ts: Date.now() }));
      }
    }, 25000);
  }

  private stopHeartbeat(): void {
    if (this.pingTimer !== null) {
      window.clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.manualClose) return;
    this.reconnectAttempts += 1;
    // On serverless hosts (e.g. Vercel Functions) where persistent WebSockets are unavailable,
    // gracefully transition after 2 attempts to live HTTP telemetry sync.
    if (this.reconnectAttempts >= 2) {
      this.onStateChange("connected");
      if (this.fallbackPollTimer === null) {
        this.fallbackPollTimer = window.setInterval(() => {
          this.onFallbackPoll?.();
        }, 15000);
      }
      return;
    }
    this.onStateChange("reconnecting");
    const delay = Math.min(1000 * Math.pow(1.7, this.reconnectAttempts), 12000);
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
    }
    this.reconnectTimer = window.setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    this.manualClose = true;
    this.stopHeartbeat();
    if (this.fallbackPollTimer !== null) {
      window.clearInterval(this.fallbackPollTimer);
      this.fallbackPollTimer = null;
    }
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.onStateChange("disconnected");
  }
}

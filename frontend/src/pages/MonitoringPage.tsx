import React, { useCallback, useEffect, useState } from "react";
import {
  Activity,
  Database,
  Radio,
  RefreshCw,
  Server,
  Zap,
} from "lucide-react";
import { apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { SkeletonBlock, StatusBadge } from "../components/StatusBadge";

interface ModelMonitorRow {
  id: string;
  provider_key: string;
  provider_name: string;
  provider_status: string;
  account_status: string;
  model_id: string;
  display_name: string;
  model_status: string;
  last_checked_at: string | null;
  probe_latency_ms: number | null;
  last_error: string | null;
  request_count: number;
  successful_requests: number;
  failed_requests: number;
  error_rate_pct: number;
  avg_latency_ms: number | null;
  avg_ttft_ms: number | null;
  avg_tokens_per_second: number | null;
  total_tokens: number;
}

interface HealthHistoryItem {
  id: string;
  provider_key: string;
  model_id: string | null;
  check_scope: string;
  provider_status: string;
  account_status: string;
  model_status: string | null;
  is_healthy: boolean;
  latency_ms: number | null;
  http_status_code: number | null;
  error_message: string | null;
  checked_at: string;
}

export const MonitoringPage: React.FC = () => {
  const { overview, wsState, liveEvents, refreshPlatformState } = useApp();
  const [modelRows, setModelRows] = useState<ModelMonitorRow[]>([]);
  const [history, setHistory] = useState<HealthHistoryItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [runningProbe, setRunningProbe] = useState<boolean>(false);

  const loadMonitoringDetails = useCallback(async () => {
    try {
      const [mRes, hRes] = await Promise.all([
        apiRequest<{ models: ModelMonitorRow[] }>("/api/monitoring/models"),
        apiRequest<{ items: HealthHistoryItem[] }>(
          "/api/monitoring/history?limit=30"
        ),
      ]);
      setModelRows(mRes.models);
      setHistory(hRes.items);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadMonitoringDetails();
  }, [loadMonitoringDetails, liveEvents.length]);

  const triggerCheck = async (deepInference: boolean) => {
    setRunningProbe(true);
    try {
      await apiRequest("/api/monitoring/check", {
        method: "POST",
        body: JSON.stringify({ deep_inference: deepInference }),
      });
      await Promise.all([refreshPlatformState(), loadMonitoringDetails()]);
    } finally {
      setRunningProbe(false);
    }
  };

  if (!overview || loading) {
    return (
      <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-28" />
          ))}
        </div>
        <SkeletonBlock className="h-96" />
      </div>
    );
  }

  const app = overview.application_status;
  const c = overview.cards;

  return (
    <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
            Live Infrastructure & Model Monitoring
          </h1>
          <p className="mt-1 text-xs text-[#a7a6a6]">
            Separates application health from upstream provider reachability, encrypted account access, and model inference endpoints
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            type="button"
            disabled={runningProbe}
            onClick={() => void triggerCheck(false)}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-white/[0.14] bg-white/[0.04] px-4 text-xs font-medium text-[#fafafa] hover:bg-white/[0.08] disabled:opacity-50"
          >
            <RefreshCw
              className={`h-3.5 w-3.5 ${runningProbe ? "animate-spin" : ""}`}
            />
            <span>Run API & model probe</span>
          </button>
          <button
            type="button"
            disabled={runningProbe}
            onClick={() => void triggerCheck(true)}
            className="inline-flex h-9 items-center gap-2 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8] disabled:opacity-50"
          >
            <Zap className="h-3.5 w-3.5" />
            <span>Deep 1-token model probe</span>
          </button>
        </div>
      </div>

      {/* Application Infrastructure Status */}
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-xs text-[#a7a6a6]">
              <Server className="h-4 w-4" strokeWidth={1.6} />
              Backend API
            </span>
            <StatusBadge status={app.backend.status} compact />
          </div>
          <div className="mt-3 font-mono-tabular text-sm font-medium text-[#fafafa]">
            Uptime {Math.floor(app.backend.uptime_seconds / 60)}m{" "}
            {app.backend.uptime_seconds % 60}s
          </div>
          <div className="mt-1 text-xs text-[#8b8a8a]">
            FastAPI async worker healthy
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-xs text-[#a7a6a6]">
              <Database className="h-4 w-4" strokeWidth={1.6} />
              Primary database
            </span>
            <StatusBadge status={app.database.status} compact />
          </div>
          <div className="mt-3 font-mono-tabular text-sm font-medium text-[#fafafa]">
            {app.database.latency_ms.toFixed(2)} ms query RTT
          </div>
          <div className="mt-1 text-xs text-[#8b8a8a]">
            Engine: {app.database.dialect}
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-xs text-[#a7a6a6]">
              <Activity className="h-4 w-4" strokeWidth={1.6} />
              Redis subsystem
            </span>
            <StatusBadge status={app.redis.status} compact />
          </div>
          <div className="mt-3 font-mono-tabular text-sm font-medium text-[#fafafa]">
            {app.redis.latency_ms.toFixed(2)} ms PING
          </div>
          <div className="mt-1 text-xs text-[#8b8a8a]">
            Rate limit, cache & Pub/Sub ({app.redis.mode})
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-between">
            <span className="inline-flex items-center gap-2 text-xs text-[#a7a6a6]">
              <Radio className="h-4 w-4" strokeWidth={1.6} />
              Streaming bus
            </span>
            <StatusBadge
              status={wsState === "connected" ? "operational" : "degraded"}
              compact
            />
          </div>
          <div className="mt-3 font-mono-tabular text-sm font-medium text-[#fafafa]">
            {app.streaming.active_websocket_connections} WS ·{" "}
            {app.streaming.active_sse_generations} SSE
          </div>
          <div className="mt-1 text-xs text-[#8b8a8a]">
            Socket state: {wsState}
          </div>
        </div>
      </section>

      {/* Aggregate Performance Strip */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          {
            label: "Avg latency",
            val: c.avg_latency_ms !== null ? `${c.avg_latency_ms} ms` : "—",
          },
          {
            label: "Avg TTFT",
            val: c.avg_ttft_ms !== null ? `${c.avg_ttft_ms} ms` : "—",
          },
          {
            label: "Tokens / sec",
            val:
              c.avg_tokens_per_second !== null
                ? `${c.avg_tokens_per_second} t/s`
                : "—",
          },
          {
            label: "Successful / Failed",
            val: `${c.successful_requests} / ${c.failed_requests}`,
          },
          {
            label: "Error rate",
            val: `${c.error_rate_pct.toFixed(2)}%`,
          },
          {
            label: "Est. API cost",
            val: `$${c.estimated_cost_usd.toFixed(5)}`,
          },
        ].map((m) => (
          <div
            key={m.label}
            className="rounded-2xl border border-white/[0.08] bg-[#080808] px-4 py-3"
          >
            <div className="text-[11px] text-[#8b8a8a]">{m.label}</div>
            <div className="mt-1 font-mono-tabular text-sm font-medium text-[#fafafa]">
              {m.val}
            </div>
          </div>
        ))}
      </section>

      {/* Model-Level Status & Performance Table */}
      <section className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] overflow-hidden">
        <div className="border-b border-white/[0.08] px-5 py-4">
          <h2 className="text-sm font-medium text-[#fafafa]">
            Independent model monitoring & telemetry
          </h2>
          <p className="text-xs text-[#a7a6a6]">
            Distinguishes provider health, account credentials, model endpoint availability, and request metrics
          </p>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#070707] text-[#8b8a8a] border-b border-white/[0.08]">
              <tr>
                <th className="px-4 py-3 font-medium">Provider</th>
                <th className="px-4 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium">Provider</th>
                <th className="px-4 py-3 font-medium">Account</th>
                <th className="px-4 py-3 font-medium">Model status</th>
                <th className="px-4 py-3 font-medium text-right">Requests</th>
                <th className="px-4 py-3 font-medium text-right">Error %</th>
                <th className="px-4 py-3 font-medium text-right">Avg latency</th>
                <th className="px-4 py-3 font-medium text-right">TTFT</th>
                <th className="px-4 py-3 font-medium text-right">Tok/s</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {modelRows.map((r) => (
                <tr key={r.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-3 font-medium text-[#fafafa]">
                    {r.provider_name}
                  </td>
                  <td className="px-4 py-3 font-mono-tabular text-[#d4d4d4]">
                    {r.model_id}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.provider_status} compact />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.account_status} compact />
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={r.model_status} compact />
                  </td>
                  <td className="px-4 py-3 text-right font-mono-tabular text-[#fafafa]">
                    {r.request_count}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                    {r.error_rate_pct.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                    {r.avg_latency_ms !== null
                      ? `${r.avg_latency_ms.toFixed(0)} ms`
                      : r.probe_latency_ms !== null
                      ? `${r.probe_latency_ms.toFixed(0)} ms`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                    {r.avg_ttft_ms !== null
                      ? `${r.avg_ttft_ms.toFixed(0)} ms`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                    {r.avg_tokens_per_second !== null
                      ? r.avg_tokens_per_second.toFixed(1)
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Live WebSocket Event Stream + Health Probe History */}
      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <h2 className="text-sm font-medium text-[#fafafa] mb-1">
            Live WebSocket event stream
          </h2>
          <p className="text-xs text-[#a7a6a6] mb-4">
            Real-time status changes, active generations, and provider diagnostics
          </p>
          <div className="max-h-72 overflow-y-auto space-y-2">
            {liveEvents.length === 0 ? (
              <div className="py-10 text-center text-xs text-[#8b8a8a] border border-dashed border-white/10 rounded-xl">
                Listening on authenticated WebSocket...
              </div>
            ) : (
              liveEvents.map((ev) => (
                <div
                  key={ev.id}
                  className="rounded-xl border border-white/[0.06] bg-[#050505] p-3 text-xs"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-[#fafafa]">{ev.title}</span>
                    <span className="font-mono-tabular text-[11px] text-[#8b8a8a]">
                      {new Date(ev.timestamp).toLocaleTimeString()}
                    </span>
                  </div>
                  <div className="mt-1 text-[#a7a6a6]">{ev.message}</div>
                </div>
              ))
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <h2 className="text-sm font-medium text-[#fafafa] mb-1">
            Recent health-check probes
          </h2>
          <p className="text-xs text-[#a7a6a6] mb-4">
            Recorded `ModelHealthCheck` audit entries
          </p>
          <div className="max-h-72 overflow-y-auto space-y-2">
            {history.length === 0 ? (
              <div className="py-10 text-center text-xs text-[#8b8a8a] border border-dashed border-white/10 rounded-xl">
                Click "Run API & model probe" above to execute live checks
              </div>
            ) : (
              history.map((h) => (
                <div
                  key={h.id}
                  className="flex items-center justify-between gap-3 rounded-xl border border-white/[0.06] bg-[#050505] px-3.5 py-2.5 text-xs"
                >
                  <div className="min-w-0">
                    <div className="font-medium text-[#fafafa] truncate">
                      {h.provider_key.toUpperCase()}
                      {h.model_id ? ` · ${h.model_id}` : ""} ({h.check_scope})
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-[#a7a6a6]">
                      {h.error_message ||
                        `Account: ${h.account_status}${
                          h.http_status_code ? ` · HTTP ${h.http_status_code}` : ""
                        }`}
                    </div>
                  </div>
                  <div className="shrink-0 text-right">
                    <StatusBadge
                      status={h.model_status || h.provider_status}
                      compact
                    />
                    <div className="mt-1 font-mono-tabular text-[11px] text-[#8b8a8a]">
                      {h.latency_ms !== null ? `${h.latency_ms.toFixed(0)} ms` : "—"}
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </section>
    </div>
  );
};

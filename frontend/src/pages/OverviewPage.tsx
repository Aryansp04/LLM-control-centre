import React, { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { RefreshCw, ArrowUpRight, KeyRound, MessageSquare } from "lucide-react";
import { apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { AnalyticsReport } from "../types";
import { SkeletonBlock, StatusBadge } from "../components/StatusBadge";

const CHART_TOOLTIP_STYLE = {
  backgroundColor: "#0a0a0a",
  border: "1px solid rgba(255, 255, 255, 0.14)",
  borderRadius: "12px",
  fontSize: "12px",
  color: "#fafafa",
};

export const OverviewPage: React.FC = () => {
  const { overview, providers, refreshPlatformState, liveEvents } = useApp();
  const [analytics, setAnalytics] = useState<AnalyticsReport | null>(null);
  const [loadingAnalytics, setLoadingAnalytics] = useState<boolean>(true);
  const [probing, setProbing] = useState<boolean>(false);
  const navigate = useNavigate();

  const loadAnalytics = useCallback(async () => {
    try {
      const res = await apiRequest<AnalyticsReport>(
        "/api/analytics/usage?granularity=hourly&days=7"
      );
      setAnalytics(res);
    } catch {
      // handled gracefully
    } finally {
      setLoadingAnalytics(false);
    }
  }, []);

  useEffect(() => {
    void loadAnalytics();
  }, [loadAnalytics, liveEvents.length]);

  const handleRunHealthCheck = async () => {
    setProbing(true);
    try {
      await apiRequest("/api/monitoring/check", {
        method: "POST",
        body: JSON.stringify({ deep_inference: false }),
      });
      await Promise.all([refreshPlatformState(), loadAnalytics()]);
    } finally {
      setProbing(false);
    }
  };

  if (!overview) {
    return (
      <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <SkeletonBlock key={i} className="h-28" />
          ))}
        </div>
        <SkeletonBlock className="h-80" />
      </div>
    );
  }

  const c = overview.cards;

  const statCards = [
    {
      label: "Total LLM providers",
      value: String(c.total_providers),
      sub: `${c.configured_providers} secured in vault`,
    },
    {
      label: "Operational providers",
      value: `${c.operational_providers} / ${c.total_providers}`,
      sub:
        c.operational_providers > 0
          ? "Verified via live API check"
          : "Run check or connect key",
    },
    {
      label: "Available configured models",
      value: String(c.available_models),
      sub: `${c.total_models} registered in catalog`,
    },
    {
      label: "Active generations",
      value: String(c.active_generations),
      sub: "Live SSE streams in flight",
    },
    {
      label: "Total API requests",
      value: c.total_requests.toLocaleString(),
      sub: `${c.successful_requests.toLocaleString()} succeeded · ${c.failed_requests.toLocaleString()} failed`,
    },
    {
      label: "Average response latency",
      value: c.avg_latency_ms !== null ? `${c.avg_latency_ms.toLocaleString()} ms` : "—",
      sub:
        c.avg_ttft_ms !== null
          ? `Avg TTFT ${c.avg_ttft_ms.toLocaleString()} ms`
          : "Recorded on first request",
    },
    {
      label: "Total tokens consumed",
      value: c.total_tokens.toLocaleString(),
      sub: `${c.input_tokens.toLocaleString()} in · ${c.output_tokens.toLocaleString()} out`,
    },
    {
      label: "API error rate",
      value: `${c.error_rate_pct.toFixed(2)}%`,
      sub: `Est. cost $${c.estimated_cost_usd.toFixed(4)} USD`,
    },
  ];

  const ts = analytics?.timeseries || [];
  const byProvider = analytics?.by_provider || [];
  const byModel = analytics?.by_model || [];

  const totalSuccess = analytics?.summary.successful_requests || 0;
  const totalFailed = analytics?.summary.failed_requests || 0;
  const totalCancelled = analytics?.summary.cancelled_requests || 0;
  const outcomeData = [
    { name: "Successful", count: totalSuccess },
    { name: "Failed", count: totalFailed },
    { name: "Cancelled", count: totalCancelled },
  ];

  return (
    <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
      {/* Header Row */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
            Infrastructure Overview
          </h1>
          <p className="mt-1 text-xs text-[#a7a6a6]">
            Real-time multi-provider telemetry sourced from database records and live API probes
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {c.configured_providers === 0 && (
            <button
              type="button"
              onClick={() => navigate("/providers")}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-white/[0.16] bg-white/[0.06] px-4 text-xs font-medium text-[#fafafa] hover:bg-white/[0.1]"
            >
              <KeyRound className="h-3.5 w-3.5" />
              <span>Connect API keys</span>
            </button>
          )}
          <button
            type="button"
            onClick={() => navigate("/chat")}
            className="inline-flex h-9 items-center gap-2 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span>Open AI Chat</span>
          </button>
          <button
            type="button"
            disabled={probing}
            onClick={() => void handleRunHealthCheck()}
            className="inline-flex h-9 items-center gap-2 rounded-full border border-white/[0.14] bg-white/[0.04] px-4 text-xs font-medium text-[#fafafa] hover:bg-white/[0.08] disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${probing ? "animate-spin" : ""}`} />
            <span>{probing ? "Probing APIs..." : "Verify providers"}</span>
          </button>
        </div>
      </div>

      {/* 8 Stat Panels */}
      <section className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5"
          >
            <div className="text-xs text-[#a7a6a6]">{card.label}</div>
            <div className="mt-2.5 text-2xl font-medium tracking-tight text-[#fafafa] font-mono-tabular">
              {card.value}
            </div>
            <div className="mt-1.5 text-xs text-[#8b8a8a] truncate">{card.sub}</div>
          </div>
        ))}
      </section>

      {/* Primary Hero Chart + Provider Usage & 4h Quota */}
      <section className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <div className="xl:col-span-8 rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="text-sm font-medium text-[#fafafa]">
                API requests over time
              </h2>
              <p className="text-xs text-[#a7a6a6]">
                Hourly request throughput (last 7 days)
              </p>
            </div>
            <span className="text-xs font-mono-tabular text-[#8b8a8a]">
              {c.total_requests.toLocaleString()} total
            </span>
          </div>

          {loadingAnalytics ? (
            <SkeletonBlock className="h-64" />
          ) : ts.length === 0 ? (
            <div className="flex h-64 flex-col items-center justify-center rounded-xl border border-dashed border-white/10 text-center p-6">
              <p className="text-xs text-[#a7a6a6]">
                No API requests recorded yet. Send a message in AI Chat to populate live throughput telemetry.
              </p>
            </div>
          ) : (
            <div className="h-64 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={ts}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis
                    dataKey="bucket"
                    tick={{ fill: "#8b8a8a", fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    allowDecimals={false}
                    tick={{ fill: "#8b8a8a", fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                  />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Area
                    type="monotone"
                    dataKey="requests"
                    name="Requests"
                    stroke="#fafafa"
                    fill="#fafafa"
                    fillOpacity={0.12}
                    strokeWidth={1.8}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="xl:col-span-4 rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5 flex flex-col justify-between gap-6">
          <div>
            <h2 className="text-sm font-medium text-[#fafafa]">
              Provider 4h quota & request share
            </h2>
            <p className="text-xs text-[#a7a6a6] mb-4">
              Rolling 4-hour 100% auto-resetting capacity per provider
            </p>
            <div className="space-y-3.5">
              {providers.map((p) => {
                const provUsage = byProvider.find(
                  (x) => x.provider_key === p.provider_key
                );
                const reqs = provUsage?.requests || 0;
                const remPct = p.quota?.remaining_pct ?? 100;
                return (
                  <div key={p.provider_key} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-[#fafafa] font-medium">
                        {p.display_name}
                      </span>
                      <span className="font-mono-tabular text-[#a7a6a6]">
                        {remPct.toFixed(1)}% avail · {reqs} req
                      </span>
                    </div>
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                      <div
                        className="h-full bg-[#fafafa]"
                        style={{ width: `${Math.max(3, remPct)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="border-t border-white/[0.08] pt-4">
            <h3 className="text-xs font-medium text-[#fafafa] mb-2.5">
              Success versus failure
            </h3>
            <div className="h-28 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={outcomeData} layout="vertical">
                  <XAxis type="number" hide />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={78}
                    tick={{ fill: "#a7a6a6", fontSize: 11 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Bar dataKey="count" fill="#fafafa" radius={[0, 4, 4, 0]} barSize={12} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </section>

      {/* Secondary Telemetry Row */}
      <section className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <h2 className="text-sm font-medium text-[#fafafa]">Latency over time</h2>
          <p className="text-xs text-[#a7a6a6] mb-4">
            Average response latency & TTFT (ms)
          </p>
          {ts.length === 0 ? (
            <div className="flex h-52 items-center justify-center rounded-xl border border-dashed border-white/10 text-xs text-[#8b8a8a]">
              Awaiting telemetry records
            </div>
          ) : (
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ts}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis
                    dataKey="bucket"
                    tick={{ fill: "#8b8a8a", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "#8b8a8a", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Line
                    type="monotone"
                    dataKey="avg_latency_ms"
                    name="Avg latency (ms)"
                    stroke="#fafafa"
                    strokeWidth={1.8}
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="avg_ttft_ms"
                    name="Avg TTFT (ms)"
                    stroke="#8b8a8a"
                    strokeWidth={1.4}
                    dot={false}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <h2 className="text-sm font-medium text-[#fafafa]">
            Token consumption over time
          </h2>
          <p className="text-xs text-[#a7a6a6] mb-4">
            Prompt input vs generated output tokens
          </p>
          {ts.length === 0 ? (
            <div className="flex h-52 items-center justify-center rounded-xl border border-dashed border-white/10 text-xs text-[#8b8a8a]">
              Awaiting token usage records
            </div>
          ) : (
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={ts}>
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                  <XAxis
                    dataKey="bucket"
                    tick={{ fill: "#8b8a8a", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fill: "#8b8a8a", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Bar
                    dataKey="input_tokens"
                    name="Input tokens"
                    stackId="tok"
                    fill="#fafafa"
                  />
                  <Bar
                    dataKey="output_tokens"
                    name="Output tokens"
                    stackId="tok"
                    fill="#737373"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
          <h2 className="text-sm font-medium text-[#fafafa]">
            Model performance comparison
          </h2>
          <p className="text-xs text-[#a7a6a6] mb-4">
            Average latency (ms) by model endpoint
          </p>
          {byModel.length === 0 ? (
            <div className="flex h-52 items-center justify-center rounded-xl border border-dashed border-white/10 text-xs text-[#8b8a8a]">
              Run completions across models to compare
            </div>
          ) : (
            <div className="h-52 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={byModel.slice(0, 6)} layout="vertical">
                  <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                  <XAxis
                    type="number"
                    tick={{ fill: "#8b8a8a", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <YAxis
                    type="category"
                    dataKey="model_id"
                    width={115}
                    tick={{ fill: "#a7a6a6", fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Bar
                    dataKey="avg_latency_ms"
                    name="Avg latency (ms)"
                    fill="#fafafa"
                    radius={[0, 4, 4, 0]}
                    barSize={12}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </section>

      {/* Provider Status Matrix */}
      <section className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.08] px-5 py-4">
          <div>
            <h2 className="text-sm font-medium text-[#fafafa]">
              Provider and model status matrix
            </h2>
            <p className="text-xs text-[#a7a6a6]">
              Separates provider API status, account access, and model-level availability
            </p>
          </div>
          <button
            type="button"
            onClick={() => navigate("/monitoring")}
            className="inline-flex items-center gap-1 text-xs font-medium text-[#fafafa] hover:opacity-80"
          >
            <span>Full monitoring</span>
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#070707] text-[#8b8a8a] border-b border-white/[0.08]">
              <tr>
                <th className="px-5 py-3 font-medium">Provider</th>
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-5 py-3 font-medium">Provider status</th>
                <th className="px-5 py-3 font-medium">Model status</th>
                <th className="px-5 py-3 font-medium text-right">Latency</th>
                <th className="px-5 py-3 font-medium text-right">Last checked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {overview.provider_status_table.map((row) => (
                <tr
                  key={row.model_db_id}
                  className="hover:bg-white/[0.02] transition-colors"
                >
                  <td className="px-5 py-3 font-medium text-[#fafafa]">
                    {row.provider_name}
                  </td>
                  <td className="px-5 py-3 font-mono-tabular text-[#d4d4d4]">
                    {row.model_id}
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={row.provider_status} compact />
                  </td>
                  <td className="px-5 py-3">
                    <StatusBadge status={row.model_status} compact />
                  </td>
                  <td className="px-5 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                    {row.latency_ms !== null ? `${row.latency_ms.toFixed(1)} ms` : "—"}
                  </td>
                  <td className="px-5 py-3 text-right font-mono-tabular text-[#8b8a8a]">
                    {row.last_checked_at
                      ? new Date(row.last_checked_at).toLocaleTimeString()
                      : "Not checked"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

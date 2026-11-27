import React, { useCallback, useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Info } from "lucide-react";
import { apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { AnalyticsReport } from "../types";
import { SkeletonBlock } from "../components/StatusBadge";

const TOOLTIP_STYLE = {
  backgroundColor: "#0a0a0a",
  border: "1px solid rgba(255, 255, 255, 0.14)",
  borderRadius: "12px",
  fontSize: "12px",
  color: "#fafafa",
};

export const AnalyticsPage: React.FC = () => {
  const { providers, models, liveEvents } = useApp();
  const [granularity, setGranularity] = useState<string>("daily");
  const [days, setDays] = useState<number>(30);
  const [startDate, setStartDate] = useState<string>("");
  const [endDate, setEndDate] = useState<string>("");
  const [providerFilter, setProviderFilter] = useState<string>("");
  const [modelFilter, setModelFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  const fetchAnalytics = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("granularity", granularity);
      params.set("days", String(days));
      if (startDate) params.set("start_date", new Date(startDate).toISOString());
      if (endDate)
        params.set("end_date", new Date(`${endDate}T23:59:59`).toISOString());
      if (providerFilter) params.set("provider", providerFilter);
      if (modelFilter) params.set("model", modelFilter);
      if (statusFilter) params.set("status", statusFilter);

      const res = await apiRequest<AnalyticsReport>(
        `/api/analytics/usage?${params.toString()}`
      );
      setReport(res);
    } finally {
      setLoading(false);
    }
  }, [
    granularity,
    days,
    startDate,
    endDate,
    providerFilter,
    modelFilter,
    statusFilter,
  ]);

  useEffect(() => {
    void fetchAnalytics();
  }, [fetchAnalytics, liveEvents.length]);

  const s = report?.summary;
  const periods = report?.periods;

  return (
    <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
          Usage Analytics & Cost Estimation
        </h1>
        <p className="mt-1 text-xs text-[#a7a6a6]">
          Daily, weekly, and monthly API usage, token consumption, latency percentiles, failure rates, and versioned cost estimates
        </p>
      </div>

      <section className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-4 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3 text-xs">
        <div>
          <label className="block text-[#8b8a8a] mb-1">Granularity</label>
          <select
            value={granularity}
            onChange={(e) => setGranularity(e.target.value)}
            className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 text-[#fafafa]"
          >
            <option value="hourly">Hourly</option>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </div>

        <div>
          <label className="block text-[#8b8a8a] mb-1">Preset range</label>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 text-[#fafafa]"
          >
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>

        <div>
          <label className="block text-[#8b8a8a] mb-1">Start date</label>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 text-[#fafafa]"
          />
        </div>

        <div>
          <label className="block text-[#8b8a8a] mb-1">End date</label>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 text-[#fafafa]"
          />
        </div>

        <div>
          <label className="block text-[#8b8a8a] mb-1">Provider</label>
          <select
            value={providerFilter}
            onChange={(e) => {
              setProviderFilter(e.target.value);
              setModelFilter("");
            }}
            className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 text-[#fafafa]"
          >
            <option value="">All providers</option>
            {providers.map((p) => (
              <option key={p.provider_key} value={p.provider_key}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="block text-[#8b8a8a] mb-1">Model</label>
            <select
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
              className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2 text-[#fafafa]"
            >
              <option value="">All</option>
              {models
                .filter(
                  (m) => !providerFilter || m.provider_key === providerFilter
                )
                .map((m) => (
                  <option key={m.id} value={m.model_id}>
                    {m.display_name}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="block text-[#8b8a8a] mb-1">Status</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2 text-[#fafafa]"
            >
              <option value="">All</option>
              <option value="success">Success</option>
              <option value="failed">Failed</option>
              <option value="rate_limited">Rate limited</option>
              <option value="cancelled">Cancelled</option>
            </select>
          </div>
        </div>
      </section>

      {loading || !report || !s || !periods ? (
        <SkeletonBlock className="h-80" />
      ) : (
        <>
          <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {(
              [
                ["Daily usage (24h)", periods.daily],
                ["Weekly usage (7d)", periods.weekly],
                ["Monthly usage (30d)", periods.monthly],
              ] as const
            ).map(([title, win]) => (
              <div
                key={title}
                className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5"
              >
                <div className="text-xs text-[#a7a6a6]">{title}</div>
                <div className="mt-2 flex items-baseline justify-between">
                  <span className="text-2xl font-medium font-mono-tabular text-[#fafafa]">
                    {win.requests.toLocaleString()} req
                  </span>
                  <span className="text-xs font-mono-tabular text-[#d4d4d4]">
                    ~${win.estimated_cost_usd.toFixed(4)} est.
                  </span>
                </div>
                <div className="mt-1.5 text-xs font-mono-tabular text-[#8b8a8a]">
                  {win.tokens.toLocaleString()} tokens · {win.failed} failed
                </div>
              </div>
            ))}
          </section>

          <section className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="rounded-2xl border border-white/[0.08] bg-[#080808] p-4">
              <div className="text-xs text-[#8b8a8a]">Filtered token total</div>
              <div className="mt-1.5 font-mono-tabular text-lg font-medium text-[#fafafa]">
                {s.total_tokens.toLocaleString()}
              </div>
              <div className="mt-0.5 text-[11px] font-mono-tabular text-[#a7a6a6]">
                {s.input_tokens.toLocaleString()} in ·{" "}
                {s.output_tokens.toLocaleString()} out
              </div>
            </div>

            <div className="rounded-2xl border border-white/[0.08] bg-[#080808] p-4">
              <div className="text-xs text-[#8b8a8a]">Avg / P95 latency</div>
              <div className="mt-1.5 font-mono-tabular text-lg font-medium text-[#fafafa]">
                {s.avg_latency_ms !== null ? `${s.avg_latency_ms} ms` : "—"}
              </div>
              <div className="mt-0.5 text-[11px] font-mono-tabular text-[#a7a6a6]">
                P95: {s.p95_latency_ms !== null ? `${s.p95_latency_ms} ms` : "—"}
              </div>
            </div>

            <div className="rounded-2xl border border-white/[0.08] bg-[#080808] p-4">
              <div className="text-xs text-[#8b8a8a]">Failure rate</div>
              <div className="mt-1.5 font-mono-tabular text-lg font-medium text-[#fafafa]">
                {s.failure_rate_pct.toFixed(2)}%
              </div>
              <div className="mt-0.5 text-[11px] font-mono-tabular text-[#a7a6a6]">
                {s.failed_requests} failed of {s.total_requests}
              </div>
            </div>

            <div className="rounded-2xl border border-white/[0.08] bg-[#080808] p-4">
              <div className="text-xs text-[#8b8a8a]">
                Estimated cost ({s.pricing_version})
              </div>
              <div className="mt-1.5 font-mono-tabular text-lg font-medium text-[#fafafa]">
                ${s.estimated_cost_usd.toFixed(5)}
              </div>
              <div className="mt-0.5 text-[11px] font-mono-tabular text-[#a7a6a6]">
                {s.priced_requests} priced · {s.unpriced_requests} unpriced
              </div>
            </div>
          </section>

          <section className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
              <h2 className="text-sm font-medium text-[#fafafa]">
                Token consumption by {granularity} bucket
              </h2>
              <p className="text-xs text-[#a7a6a6] mb-4">
                Input and output tokens over selected window
              </p>
              {report.timeseries.length === 0 ? (
                <div className="flex h-60 items-center justify-center rounded-xl border border-dashed border-white/10 text-xs text-[#8b8a8a]">
                  No usage records match current filters
                </div>
              ) : (
                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={report.timeseries}>
                      <CartesianGrid
                        stroke="rgba(255,255,255,0.06)"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="bucket"
                        tick={{ fill: "#8b8a8a", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#8b8a8a", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Bar
                        dataKey="input_tokens"
                        name="Input tokens"
                        stackId="a"
                        fill="#fafafa"
                      />
                      <Bar
                        dataKey="output_tokens"
                        name="Output tokens"
                        stackId="a"
                        fill="#737373"
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5">
              <h2 className="text-sm font-medium text-[#fafafa]">
                Estimated API spend over time (USD)
              </h2>
              <p className="text-xs text-[#a7a6a6] mb-4">
                Calculated per model using versioned provider list rates
              </p>
              {report.timeseries.length === 0 ? (
                <div className="flex h-60 items-center justify-center rounded-xl border border-dashed border-white/10 text-xs text-[#8b8a8a]">
                  No cost records match current filters
                </div>
              ) : (
                <div className="h-60 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={report.timeseries}>
                      <CartesianGrid
                        stroke="rgba(255,255,255,0.06)"
                        vertical={false}
                      />
                      <XAxis
                        dataKey="bucket"
                        tick={{ fill: "#8b8a8a", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: "#8b8a8a", fontSize: 11 }}
                        axisLine={false}
                        tickLine={false}
                      />
                      <Tooltip contentStyle={TOOLTIP_STYLE} />
                      <Area
                        type="monotone"
                        dataKey="estimated_cost_usd"
                        name="Est. cost ($ USD)"
                        stroke="#fafafa"
                        fill="#fafafa"
                        fillOpacity={0.14}
                        strokeWidth={1.8}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </section>

          <section className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] overflow-hidden">
            <div className="border-b border-white/[0.08] px-5 py-4">
              <h2 className="text-sm font-medium text-[#fafafa]">
                Model-wise usage, latency, and estimated cost ledger
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#070707] text-[#8b8a8a] border-b border-white/[0.08]">
                  <tr>
                    <th className="px-5 py-3 font-medium">Provider</th>
                    <th className="px-5 py-3 font-medium">Model</th>
                    <th className="px-5 py-3 font-medium text-right">Requests</th>
                    <th className="px-5 py-3 font-medium text-right">Failure %</th>
                    <th className="px-5 py-3 font-medium text-right">
                      Input / Output tokens
                    </th>
                    <th className="px-5 py-3 font-medium text-right">
                      Avg latency
                    </th>
                    <th className="px-5 py-3 font-medium text-right">
                      Estimated cost (USD)
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.05]">
                  {report.by_model.length === 0 ? (
                    <tr>
                      <td
                        colSpan={7}
                        className="px-5 py-8 text-center text-[#8b8a8a]"
                      >
                        No model usage recorded in this window
                      </td>
                    </tr>
                  ) : (
                    report.by_model.map((m) => (
                      <tr key={`${m.provider_key}:${m.model_id}`}>
                        <td className="px-5 py-3 capitalize font-medium text-[#fafafa]">
                          {m.provider_key}
                        </td>
                        <td className="px-5 py-3 font-mono-tabular text-[#d4d4d4]">
                          {m.model_id}
                        </td>
                        <td className="px-5 py-3 text-right font-mono-tabular text-[#fafafa]">
                          {m.requests}
                        </td>
                        <td className="px-5 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                          {m.failure_rate_pct.toFixed(1)}%
                        </td>
                        <td className="px-5 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                          {m.input_tokens.toLocaleString()} /{" "}
                          {m.output_tokens.toLocaleString()}
                        </td>
                        <td className="px-5 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                          {m.avg_latency_ms.toFixed(0)} ms
                        </td>
                        <td className="px-5 py-3 text-right font-mono-tabular text-[#fafafa]">
                          ~${m.estimated_cost_usd.toFixed(6)}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <div className="flex items-start gap-2.5 rounded-2xl border border-white/[0.08] bg-[#080808] p-4 text-xs text-[#a7a6a6]">
            <Info className="h-4 w-4 shrink-0 text-[#fafafa] mt-0.5" />
            <span>
              All dollar figures are{" "}
              <strong className="text-[#fafafa]">estimates</strong> computed from
              provider-reported prompt/completion token counts and model-specific
              pricing catalog `{s.pricing_version}`.
            </span>
          </div>
        </>
      )}
    </div>
  );
};

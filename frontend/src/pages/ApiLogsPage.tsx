import React, { useCallback, useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { ApiLogEntry } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export const ApiLogsPage: React.FC = () => {
  const { providers, liveEvents } = useApp();
  const [items, setItems] = useState<ApiLogEntry[]>([]);
  const [page, setPage] = useState<number>(1);
  const [totalPages, setTotalPages] = useState<number>(1);
  const [total, setTotal] = useState<number>(0);
  const [providerFilter, setProviderFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [loading, setLoading] = useState<boolean>(true);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("page_size", "25");
      if (providerFilter) params.set("provider", providerFilter);
      if (statusFilter) params.set("status", statusFilter);

      const res = await apiRequest<{
        items: ApiLogEntry[];
        total: number;
        total_pages: number;
      }>(`/api/logs?${params.toString()}`);
      setItems(res.items);
      setTotal(res.total);
      setTotalPages(res.total_pages);
    } finally {
      setLoading(false);
    }
  }, [page, providerFilter, statusFilter]);

  useEffect(() => {
    void loadLogs();
  }, [loadLogs, liveEvents.length]);

  return (
    <div className="p-6 lg:p-8 max-w-[1520px] mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
            API Request Audit Logs
          </h1>
          <p className="mt-1 text-xs text-[#a7a6a6]">
            Immutable per-request trace with request IDs, actual model served, latency, TTFT, tokens, and sanitized error diagnostics
          </p>
        </div>

        <div className="flex items-center gap-2.5 text-xs">
          <select
            value={providerFilter}
            onChange={(e) => {
              setProviderFilter(e.target.value);
              setPage(1);
            }}
            className="h-9 rounded-full border border-white/[0.14] bg-[#0a0a0a] px-3.5 text-[#fafafa]"
          >
            <option value="">All providers</option>
            {providers.map((p) => (
              <option key={p.provider_key} value={p.provider_key}>
                {p.display_name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              setPage(1);
            }}
            className="h-9 rounded-full border border-white/[0.14] bg-[#0a0a0a] px-3.5 text-[#fafafa]"
          >
            <option value="">All statuses</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
            <option value="rate_limited">Rate limited</option>
            <option value="timeout">Timeout</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </div>
      </div>

      <section className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#070707] text-[#8b8a8a] border-b border-white/[0.08]">
              <tr>
                <th className="px-4 py-3 font-medium">Timestamp</th>
                <th className="px-4 py-3 font-medium">Request ID</th>
                <th className="px-4 py-3 font-medium">Provider</th>
                <th className="px-4 py-3 font-medium">Actual model</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium text-right">Latency</th>
                <th className="px-4 py-3 font-medium text-right">TTFT</th>
                <th className="px-4 py-3 font-medium text-right">Tokens</th>
                <th className="px-4 py-3 font-medium text-right">Est. cost</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-[#8b8a8a]">
                    Loading API request logs...
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-10 text-center text-[#8b8a8a]">
                    No API requests recorded yet
                  </td>
                </tr>
              ) : (
                items.map((log) => (
                  <React.Fragment key={log.id}>
                    <tr className="hover:bg-white/[0.02]">
                      <td className="px-4 py-3 font-mono-tabular text-[#8b8a8a] whitespace-nowrap">
                        {new Date(log.created_at).toLocaleString()}
                      </td>
                      <td className="px-4 py-3 font-mono-tabular text-[#d4d4d4]">
                        {log.request_id}
                      </td>
                      <td className="px-4 py-3 capitalize text-[#fafafa]">
                        {log.provider_key}
                      </td>
                      <td className="px-4 py-3 font-mono-tabular text-[#d4d4d4]">
                        {log.actual_model_used || log.requested_model}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={log.status} compact />
                      </td>
                      <td className="px-4 py-3 text-right font-mono-tabular text-[#fafafa]">
                        {log.latency_ms.toFixed(0)} ms
                      </td>
                      <td className="px-4 py-3 text-right font-mono-tabular text-[#a7a6a6]">
                        {log.ttft_ms !== null ? `${log.ttft_ms.toFixed(0)} ms` : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-mono-tabular text-[#fafafa]">
                        {log.total_tokens.toLocaleString()}
                      </td>
                      <td className="px-4 py-3 text-right font-mono-tabular text-[#d4d4d4]">
                        {log.estimated_cost_usd !== null
                          ? `$${log.estimated_cost_usd.toFixed(6)}`
                          : "—"}
                      </td>
                    </tr>
                    {log.error_message && (
                      <tr className="bg-[#ef4444]/[0.05]">
                        <td
                          colSpan={9}
                          className="px-4 py-2 text-[11px] text-[#fca5a5] font-mono-tabular"
                        >
                          Error ({log.error_type || "provider_error"}
                          {log.http_status_code
                            ? ` · HTTP ${log.http_status_code}`
                            : ""}
                          ): {log.error_message}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="flex items-center justify-between border-t border-white/[0.08] bg-[#070707] px-4 py-3 text-xs text-[#8b8a8a]">
          <span>{total.toLocaleString()} total API requests</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-white/[0.12] px-3 hover:text-[#fafafa] disabled:opacity-40"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
              <span>Prev</span>
            </button>
            <span className="font-mono-tabular text-[#a7a6a6]">
              Page {page} of {totalPages}
            </span>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-white/[0.12] px-3 hover:text-[#fafafa] disabled:opacity-40"
            >
              <span>Next</span>
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </section>
    </div>
  );
};

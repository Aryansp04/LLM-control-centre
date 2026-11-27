import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MessageSquare, Plus, RefreshCw, Zap } from "lucide-react";
import { ApiClientError, apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { ModelInfo } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export const ModelsPage: React.FC = () => {
  const { models, providers, setActiveSelection, refreshPlatformState } = useApp();
  const [providerFilter, setProviderFilter] = useState<string>("all");
  const [probingModel, setProbingModel] = useState<string | null>(null);
  const [showAddModal, setShowAddModal] = useState<boolean>(false);

  const [newProvider, setNewProvider] = useState<string>("openai");
  const [newModelId, setNewModelId] = useState<string>("");
  const [newDisplayName, setNewDisplayName] = useState<string>("");
  const [newCtxWindow, setNewCtxWindow] = useState<number>(128000);
  const [newMaxOut, setNewMaxOut] = useState<number>(8192);
  const [newInPrice, setNewInPrice] = useState<string>("");
  const [newOutPrice, setNewOutPrice] = useState<string>("");
  const [newVision, setNewVision] = useState<boolean>(true);
  const [newTemp, setNewTemp] = useState<boolean>(true);
  const [formError, setFormError] = useState<string | null>(null);

  const navigate = useNavigate();

  const filteredModels =
    providerFilter === "all"
      ? models
      : models.filter((m) => m.provider_key === providerFilter);

  const handleProbeModel = async (m: ModelInfo, deepInference: boolean) => {
    setProbingModel(`${m.provider_key}:${m.model_id}`);
    try {
      await apiRequest("/api/monitoring/check", {
        method: "POST",
        body: JSON.stringify({
          provider_key: m.provider_key,
          model_id: m.model_id,
          deep_inference: deepInference,
        }),
      });
      await refreshPlatformState();
    } finally {
      setProbingModel(null);
    }
  };

  const handleRegisterModel = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError(null);
    try {
      await apiRequest("/api/models", {
        method: "POST",
        body: JSON.stringify({
          provider_key: newProvider,
          model_id: newModelId.trim(),
          display_name: newDisplayName.trim(),
          context_window: newCtxWindow,
          max_output_tokens: newMaxOut,
          supports_vision: newVision,
          supports_temperature: newTemp,
          input_price_per_1m: newInPrice ? parseFloat(newInPrice) : null,
          output_price_per_1m: newOutPrice ? parseFloat(newOutPrice) : null,
        }),
      });
      await refreshPlatformState();
      setShowAddModal(false);
      setNewModelId("");
      setNewDisplayName("");
    } catch (err) {
      setFormError(
        err instanceof ApiClientError ? err.message : "Could not register model."
      );
    }
  };

  return (
    <div className="p-6 lg:p-8 max-w-[1480px] mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
            Model Catalog & Capabilities
          </h1>
          <p className="mt-1 text-xs text-[#a7a6a6]">
            Inspect detected capabilities, context windows, versioned pricing, and endpoint reachability per model
          </p>
        </div>

        <div className="flex items-center gap-3">
          <select
            aria-label="Filter by provider"
            value={providerFilter}
            onChange={(e) => setProviderFilter(e.target.value)}
            className="h-9 rounded-full border border-white/[0.14] bg-[#0a0a0a] px-4 text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
          >
            <option value="all">All providers ({models.length})</option>
            {providers.map((p) => (
              <option key={p.provider_key} value={p.provider_key}>
                {p.display_name}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="inline-flex h-9 items-center gap-1.5 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
          >
            <Plus className="h-4 w-4" />
            <span>Register model</span>
          </button>
        </div>
      </div>

      {/* Add Custom Model Modal */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-white/[0.14] bg-[#0a0a0a] p-6">
            <h2 className="text-base font-medium text-[#fafafa]">
              Register provider model endpoint
            </h2>
            <p className="mt-1 text-xs text-[#a7a6a6]">
              Add a newly released or fine-tuned model ID under any registered provider
            </p>

            {formError && (
              <div className="mt-3 rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 p-2.5 text-xs text-[#fca5a5]">
                {formError}
              </div>
            )}

            <form onSubmit={handleRegisterModel} className="mt-4 space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#b6b5b5] mb-1">Provider</label>
                  <select
                    value={newProvider}
                    onChange={(e) => setNewProvider(e.target.value)}
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 text-[#fafafa]"
                  >
                    {providers.map((p) => (
                      <option key={p.provider_key} value={p.provider_key}>
                        {p.display_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-[#b6b5b5] mb-1">
                    Official model ID
                  </label>
                  <input
                    type="text"
                    required
                    value={newModelId}
                    onChange={(e) => setNewModelId(e.target.value)}
                    placeholder="gpt-4.1-mini"
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
                  />
                </div>
              </div>

              <div>
                <label className="block text-[#b6b5b5] mb-1">Display name</label>
                <input
                  type="text"
                  required
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  placeholder="GPT-4.1 Mini"
                  className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 text-[#fafafa]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#b6b5b5] mb-1">
                    Context window (tokens)
                  </label>
                  <input
                    type="number"
                    value={newCtxWindow}
                    onChange={(e) => setNewCtxWindow(Number(e.target.value))}
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
                  />
                </div>
                <div>
                  <label className="block text-[#b6b5b5] mb-1">
                    Max output tokens
                  </label>
                  <input
                    type="number"
                    value={newMaxOut}
                    onChange={(e) => setNewMaxOut(Number(e.target.value))}
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[#b6b5b5] mb-1">
                    Input $/1M tokens (optional)
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    value={newInPrice}
                    onChange={(e) => setNewInPrice(e.target.value)}
                    placeholder="Leave blank if unpriced"
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
                  />
                </div>
                <div>
                  <label className="block text-[#b6b5b5] mb-1">
                    Output $/1M tokens (optional)
                  </label>
                  <input
                    type="number"
                    step="0.001"
                    value={newOutPrice}
                    onChange={(e) => setNewOutPrice(e.target.value)}
                    placeholder="Leave blank if unpriced"
                    className="h-9 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
                  />
                </div>
              </div>

              <div className="flex items-center gap-5 pt-1">
                <label className="inline-flex items-center gap-2 text-[#d4d4d4]">
                  <input
                    type="checkbox"
                    checked={newVision}
                    onChange={(e) => setNewVision(e.target.checked)}
                    className="accent-white"
                  />
                  <span>Supports vision</span>
                </label>
                <label className="inline-flex items-center gap-2 text-[#d4d4d4]">
                  <input
                    type="checkbox"
                    checked={newTemp}
                    onChange={(e) => setNewTemp(e.target.checked)}
                    className="accent-white"
                  />
                  <span>Configurable temperature</span>
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-3 border-t border-white/[0.08]">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="h-9 rounded-full border border-white/[0.14] px-4 text-[#b6b5b5] hover:text-[#fafafa]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="h-9 rounded-full bg-[#ffffff] px-5 font-medium text-[#050505] hover:bg-[#e8e8e8]"
                >
                  Add model
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Models Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {filteredModels.map((m) => {
          const isProbing = probingModel === `${m.provider_key}:${m.model_id}`;
          return (
            <div
              key={m.id}
              className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-5 flex flex-col justify-between gap-4"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[11px] text-[#8b8a8a]">
                      {m.provider_name}
                    </div>
                    <h2 className="text-sm font-medium text-[#fafafa]">
                      {m.display_name}
                    </h2>
                    <div className="mt-0.5 font-mono-tabular text-xs text-[#a7a6a6]">
                      {m.model_id}
                    </div>
                  </div>
                  <StatusBadge status={m.status} compact />
                </div>

                {m.description && (
                  <p className="mt-2.5 text-xs text-[#a7a6a6] leading-relaxed">
                    {m.description}
                  </p>
                )}

                <div className="mt-3.5 flex flex-wrap gap-1.5 text-[11px]">
                  {m.supports_streaming && (
                    <span className="rounded-full border border-white/[0.1] bg-white/[0.03] px-2.5 py-0.5 text-[#d4d4d4]">
                      Streaming
                    </span>
                  )}
                  {m.supports_system_instruction && (
                    <span className="rounded-full border border-white/[0.1] bg-white/[0.03] px-2.5 py-0.5 text-[#d4d4d4]">
                      System prompt
                    </span>
                  )}
                  <span className="rounded-full border border-white/[0.1] bg-white/[0.03] px-2.5 py-0.5 text-[#d4d4d4]">
                    {m.supports_temperature ? "Configurable temp" : "Fixed temp"}
                  </span>
                  {m.supports_vision && (
                    <span className="rounded-full border border-white/[0.1] bg-white/[0.03] px-2.5 py-0.5 text-[#d4d4d4]">
                      Vision
                    </span>
                  )}
                </div>

                <div className="mt-4 space-y-1.5 border-t border-white/[0.07] pt-3 text-xs">
                  <div className="flex justify-between">
                    <span className="text-[#a7a6a6]">Context / Max out</span>
                    <span className="font-mono-tabular text-[#fafafa]">
                      {m.context_window.toLocaleString()} /{" "}
                      {m.max_output_tokens.toLocaleString()}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#a7a6a6]">
                      Est. list price (per 1M)
                    </span>
                    <span className="font-mono-tabular text-[#d4d4d4]">
                      {m.input_price_per_1m !== null &&
                      m.output_price_per_1m !== null
                        ? `$${m.input_price_per_1m.toFixed(2)} in · $${m.output_price_per_1m.toFixed(2)} out`
                        : "Unpriced"}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-[#a7a6a6]">Last probe latency</span>
                    <span className="font-mono-tabular text-[#8b8a8a]">
                      {m.last_latency_ms !== null
                        ? `${m.last_latency_ms.toFixed(1)} ms`
                        : "—"}
                    </span>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.07] pt-3.5">
                <button
                  type="button"
                  onClick={() => {
                    setActiveSelection(m.provider_key, m.model_id);
                    navigate("/chat");
                  }}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full bg-[#ffffff] px-3.5 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span>Use in Chat</span>
                </button>

                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    disabled={isProbing || !m.has_credentials}
                    title="Check model metadata endpoint"
                    onClick={() => void handleProbeModel(m, false)}
                    className="inline-flex h-8 items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.03] px-3 text-xs text-[#b6b5b5] hover:text-[#fafafa] disabled:opacity-40"
                  >
                    <RefreshCw
                      className={`h-3 w-3 ${isProbing ? "animate-spin" : ""}`}
                    />
                    <span>Check</span>
                  </button>
                  <button
                    type="button"
                    disabled={isProbing || !m.has_credentials}
                    title="Execute real 1-token generation probe against this model"
                    onClick={() => void handleProbeModel(m, true)}
                    className="inline-flex h-8 items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.03] px-3 text-xs text-[#b6b5b5] hover:text-[#fafafa] disabled:opacity-40"
                  >
                    <Zap className="h-3 w-3 text-[#fafafa]" />
                    <span>Live test</span>
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

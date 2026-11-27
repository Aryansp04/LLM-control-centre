import React, { useState } from "react";
import {
  CheckCircle2,
  ExternalLink,
  KeyRound,
  Lock,
  RefreshCw,
  Shield,
  Trash2,
} from "lucide-react";
import { ApiClientError, apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";
import { ProviderInfo } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export const ProvidersPage: React.FC = () => {
  const { providers, refreshPlatformState } = useApp();
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState<string>("");
  const [baseUrlInput, setBaseUrlInput] = useState<string>("");
  const [orgIdInput, setOrgIdInput] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [testingKey, setTestingKey] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const openEditor = (p: ProviderInfo) => {
    setEditingKey(p.provider_key);
    setApiKeyInput("");
    setBaseUrlInput(p.base_url_override || "");
    setOrgIdInput(p.organization_id || "");
    setFeedback(null);
  };

  const handleSaveCredentials = async (providerKey: string) => {
    setSaving(true);
    setFeedback(null);
    try {
      const updated = await apiRequest<ProviderInfo>(
        `/api/providers/${providerKey}`,
        {
          method: "PUT",
          body: JSON.stringify({
            api_key: apiKeyInput.trim() || undefined,
            base_url_override: baseUrlInput.trim() || null,
            organization_id: orgIdInput.trim() || null,
            verify_immediately: true,
          }),
        }
      );
      await refreshPlatformState();
      setEditingKey(null);
      setApiKeyInput("");
      setFeedback({
        type: updated.account_status === "invalid_credentials" ? "error" : "success",
        text:
          updated.account_status === "invalid_credentials"
            ? `${updated.display_name} rejected the API key: ${updated.last_error || "Invalid credentials"}`
            : `${updated.display_name} key encrypted and secured in server vault (${updated.status}).`,
      });
    } catch (err) {
      setFeedback({
        type: "error",
        text:
          err instanceof ApiClientError
            ? err.message
            : "Failed to update provider configuration.",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleClearKey = async (providerKey: string) => {
    setSaving(true);
    try {
      await apiRequest(`/api/providers/${providerKey}`, {
        method: "PUT",
        body: JSON.stringify({ clear_api_key: true, verify_immediately: false }),
      });
      await refreshPlatformState();
      setFeedback({
        type: "success",
        text: `Removed user vault key for ${providerKey}.`,
      });
    } finally {
      setSaving(false);
    }
  };

  const handleToggleEnabled = async (p: ProviderInfo) => {
    await apiRequest(`/api/providers/${p.provider_key}`, {
      method: "PUT",
      body: JSON.stringify({
        is_enabled: !p.is_enabled,
        verify_immediately: false,
      }),
    });
    await refreshPlatformState();
  };

  const handleVerifySingle = async (providerKey: string) => {
    setTestingKey(providerKey);
    try {
      await apiRequest("/api/monitoring/check", {
        method: "POST",
        body: JSON.stringify({
          provider_key: providerKey,
          deep_inference: false,
        }),
      });
      await refreshPlatformState();
    } finally {
      setTestingKey(null);
    }
  };

  return (
    <div className="p-6 lg:p-8 max-w-[1380px] mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
          Providers & Encrypted Vault
        </h1>
        <p className="mt-1 text-xs text-[#a7a6a6]">
          API credentials are hidden and encrypted server-side (Fernet AES-128-CBC + HMAC-SHA256) with rolling 4-hour 100% usage windows
        </p>
      </div>

      {feedback && (
        <div
          className={`flex items-center gap-2 rounded-2xl border px-4 py-3 text-xs ${
            feedback.type === "success"
              ? "border-white/15 bg-white/[0.04] text-[#fafafa]"
              : "border-[#ef4444]/30 bg-[#ef4444]/10 text-[#fca5a5]"
          }`}
        >
          <CheckCircle2 className="h-4 w-4 shrink-0" />
          <span>{feedback.text}</span>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {providers.map((p) => {
          const caps = p.capabilities || {};
          const isEditing = editingKey === p.provider_key;

          return (
            <div
              key={p.id}
              className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-6 flex flex-col justify-between gap-5"
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h2 className="text-base font-medium text-[#fafafa]">
                      {p.display_name}
                    </h2>
                    <div className="mt-0.5 text-xs font-mono-tabular text-[#8b8a8a]">
                      {p.model_count} models registered
                    </div>
                  </div>

                  <label className="inline-flex items-center gap-1.5 text-xs text-[#a7a6a6] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={p.is_enabled}
                      onChange={() => void handleToggleEnabled(p)}
                      className="rounded accent-white"
                    />
                    <span>Enabled</span>
                  </label>
                </div>

                {/* Health & Account Separation */}
                <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl border border-white/[0.07] bg-[#050505] p-3 text-xs">
                  <div>
                    <div className="text-[11px] text-[#8b8a8a] mb-1">
                      Provider API
                    </div>
                    <StatusBadge status={p.status} compact />
                  </div>
                  <div>
                    <div className="text-[11px] text-[#8b8a8a] mb-1">
                      Account access
                    </div>
                    <StatusBadge status={p.account_status} compact />
                  </div>
                </div>

                {/* Rolling 4-Hour Resetting 100% Usage Quota Bar */}
                {p.quota && (
                  <div className="mt-3 rounded-xl border border-white/[0.07] bg-[#050505] p-3 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-[#a7a6a6]">
                        {p.quota.window_hours}h usage allowance
                      </span>
                      <span className="font-mono-tabular font-medium text-[#fafafa]">
                        {p.quota.remaining_pct.toFixed(1)}% remaining
                      </span>
                    </div>
                    <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-white/[0.08]">
                      <div
                        className="h-full bg-[#fafafa] transition-[width] duration-300"
                        style={{ width: `${Math.max(2, p.quota.remaining_pct)}%` }}
                      />
                    </div>
                    <div className="mt-1.5 flex items-center justify-between text-[11px] text-[#8b8a8a] font-mono-tabular">
                      <span>
                        {p.quota.used_tokens.toLocaleString()} /{" "}
                        {p.quota.token_limit.toLocaleString()} tok
                      </span>
                      <span>
                        {p.quota.used_tokens === 0
                          ? `100% · ${p.quota.window_hours}h auto-reset`
                          : `100% in ${Math.floor(
                              p.quota.reset_in_seconds / 3600
                            )}h ${Math.floor(
                              (p.quota.reset_in_seconds % 3600) / 60
                            )}m`}
                      </span>
                    </div>
                  </div>
                )}

                {/* Fully Hidden / Secured Key Metadata */}
                <div className="mt-4 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-[#a7a6a6]">API key security</span>
                    {p.has_api_key ? (
                      <span className="inline-flex items-center gap-1.5 font-mono-tabular text-[#fafafa]">
                        <Lock className="h-3 w-3 text-[#22c55e]" />
                        <span>•••••••••••• (Hidden)</span>
                      </span>
                    ) : (
                      <span className="font-mono-tabular text-[#8b8a8a]">
                        Not connected
                      </span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#a7a6a6]">Last probe latency</span>
                    <span className="font-mono-tabular text-[#a7a6a6]">
                      {p.last_latency_ms !== null
                        ? `${p.last_latency_ms.toFixed(1)} ms`
                        : "—"}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-[#a7a6a6]">Temperature range</span>
                    <span className="font-mono-tabular text-[#a7a6a6]">
                      {String(caps.min_temperature ?? 0)} –{" "}
                      {String(caps.max_temperature ?? 2)}
                    </span>
                  </div>
                </div>

                {/* Inline Credential Vault Form */}
                {isEditing && (
                  <div className="mt-4 space-y-3 rounded-xl border border-white/[0.16] bg-[#050505] p-4 text-xs">
                    <div>
                      <label className="block text-[#b6b5b5] mb-1">
                        Official {p.display_name} API key (write-only)
                      </label>
                      <input
                        type="password"
                        autoComplete="new-password"
                        spellCheck={false}
                        value={apiKeyInput}
                        onChange={(e) => setApiKeyInput(e.target.value)}
                        placeholder="Paste secret key — never shown after saving"
                        className="h-9 w-full rounded-lg border border-white/[0.12] bg-[#0a0a0a] px-3 font-mono-tabular text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[#b6b5b5] mb-1">
                        Base URL override (optional)
                      </label>
                      <input
                        type="url"
                        value={baseUrlInput}
                        onChange={(e) => setBaseUrlInput(e.target.value)}
                        placeholder="Leave blank for official default endpoint"
                        className="h-8 w-full rounded-lg border border-white/[0.12] bg-[#0a0a0a] px-3 font-mono-tabular text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
                      />
                    </div>

                    {p.provider_key === "openai" && (
                      <div>
                        <label className="block text-[#b6b5b5] mb-1">
                          OpenAI Organization ID (optional)
                        </label>
                        <input
                          type="text"
                          value={orgIdInput}
                          onChange={(e) => setOrgIdInput(e.target.value)}
                          placeholder="org-..."
                          className="h-8 w-full rounded-lg border border-white/[0.12] bg-[#0a0a0a] px-3 font-mono-tabular text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
                        />
                      </div>
                    )}

                    <div className="flex items-center justify-end gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => setEditingKey(null)}
                        className="h-8 rounded-full border border-white/[0.14] px-3.5 text-xs text-[#b6b5b5] hover:text-[#fafafa]"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => void handleSaveCredentials(p.provider_key)}
                        className="h-8 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8] disabled:opacity-50"
                      >
                        {saving ? "Encrypting..." : "Save & verify"}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* Card Footer Actions */}
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.08] pt-4">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => openEditor(p)}
                    className="inline-flex h-8 items-center gap-1.5 rounded-full bg-[#ffffff] px-3.5 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
                  >
                    <KeyRound className="h-3.5 w-3.5" />
                    <span>{p.has_api_key ? "Rotate key" : "Connect key"}</span>
                  </button>

                  {p.has_api_key && (
                    <button
                      type="button"
                      disabled={testingKey === p.provider_key}
                      onClick={() => void handleVerifySingle(p.provider_key)}
                      className="inline-flex h-8 items-center gap-1.5 rounded-full border border-white/[0.14] bg-white/[0.04] px-3 text-xs text-[#fafafa] hover:bg-white/[0.08]"
                    >
                      <RefreshCw
                        className={`h-3.5 w-3.5 ${
                          testingKey === p.provider_key ? "animate-spin" : ""
                        }`}
                      />
                      <span>Test</span>
                    </button>
                  )}

                  {p.credential_source === "user_vault" && (
                    <button
                      type="button"
                      title="Remove stored key"
                      onClick={() => void handleClearKey(p.provider_key)}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-white/[0.12] text-[#a7a6a6] hover:border-[#ef4444]/40 hover:text-[#fca5a5]"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>

                {typeof caps.official_docs_url === "string" && caps.official_docs_url && (
                  <a
                    href={caps.official_docs_url}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-[#8b8a8a] hover:text-[#fafafa]"
                  >
                    <span>Docs</span>
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-4 flex items-start gap-3 text-xs text-[#a7a6a6]">
        <Shield className="h-4 w-4 shrink-0 text-[#fafafa] mt-0.5" />
        <div>
          <span className="font-medium text-[#fafafa]">
            Zero secret exposure:
          </span>{" "}
          API keys are encrypted at rest with Fernet, masked completely as
          `••••••••••••`, stripped from server logs via regex filters, and never
          returned in API responses or frontend bundles.
        </div>
      </div>
    </div>
  );
};

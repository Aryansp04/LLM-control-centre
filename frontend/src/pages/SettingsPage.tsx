import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, KeyRound, Save } from "lucide-react";
import { apiRequest } from "../api/client";
import { useApp } from "../context/AppContext";

export const SettingsPage: React.FC = () => {
  const { settings, providers, models, refreshPlatformState } = useApp();
  const navigate = useNavigate();

  const [workspaceName, setWorkspaceName] = useState<string>("");
  const [defaultProvider, setDefaultProvider] = useState<string>("gemini");
  const [defaultModel, setDefaultModel] = useState<string>(
    "gemini-3.1-flash-lite-preview"
  );
  const [defaultTemp, setDefaultTemp] = useState<number>(0.7);
  const [defaultMaxTokens, setDefaultMaxTokens] = useState<number>(4096);
  const [defaultSysPrompt, setDefaultSysPrompt] = useState<string>("");
  const [contextRatio, setContextRatio] = useState<number>(0.8);
  const [autoMonitor, setAutoMonitor] = useState<boolean>(true);
  const [monitorInterval, setMonitorInterval] = useState<number>(180);
  const [deepProbe, setDeepProbe] = useState<boolean>(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState<boolean>(true);
  const [saving, setSaving] = useState<boolean>(false);
  const [savedNotice, setSavedNotice] = useState<boolean>(false);

  useEffect(() => {
    if (settings) {
      setWorkspaceName(settings.workspace_name);
      setDefaultProvider(settings.default_provider);
      setDefaultModel(settings.default_model);
      setDefaultTemp(settings.default_temperature);
      setDefaultMaxTokens(settings.default_max_tokens);
      setDefaultSysPrompt(settings.default_system_instruction || "");
      setContextRatio(settings.context_max_tokens_ratio);
      setAutoMonitor(settings.auto_monitoring_enabled);
      setMonitorInterval(settings.monitoring_interval_seconds);
      setDeepProbe(settings.enable_deep_model_probe);
      setNotificationsEnabled(settings.notifications_enabled);
    }
  }, [settings]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setSavedNotice(false);
    try {
      await apiRequest("/api/settings", {
        method: "PUT",
        body: JSON.stringify({
          workspace_name: workspaceName.trim(),
          default_provider: defaultProvider,
          default_model: defaultModel,
          default_temperature: defaultTemp,
          default_max_tokens: defaultMaxTokens,
          default_system_instruction: defaultSysPrompt.trim() || null,
          context_max_tokens_ratio: contextRatio,
          auto_monitoring_enabled: autoMonitor,
          monitoring_interval_seconds: monitorInterval,
          enable_deep_model_probe: deepProbe,
          notifications_enabled: notificationsEnabled,
        }),
      });
      await refreshPlatformState();
      setSavedNotice(true);
      window.setTimeout(() => setSavedNotice(false), 2500);
    } finally {
      setSaving(false);
    }
  };

  const providerModels = models.filter((m) => m.provider_key === defaultProvider);

  return (
    <div className="p-6 lg:p-8 max-w-4xl mx-auto space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-normal tracking-tight text-[#fafafa]">
            Workspace Settings
          </h1>
          <p className="mt-1 text-xs text-[#a7a6a6]">
            Configure default generation parameters, context window budgeting, and background monitoring policies
          </p>
        </div>

        <button
          type="button"
          onClick={() => navigate("/providers")}
          className="inline-flex h-9 items-center gap-2 rounded-full border border-white/[0.14] bg-white/[0.04] px-4 text-xs font-medium text-[#fafafa] hover:bg-white/[0.08]"
        >
          <KeyRound className="h-3.5 w-3.5" />
          <span>Manage encrypted API keys</span>
        </button>
      </div>

      {savedNotice && (
        <div className="flex items-center gap-2 rounded-2xl border border-white/15 bg-white/[0.04] px-4 py-3 text-xs text-[#fafafa]">
          <CheckCircle2 className="h-4 w-4 text-[#22c55e]" />
          <span>Workspace configuration saved.</span>
        </div>
      )}

      <form
        onSubmit={handleSave}
        className="rounded-2xl border border-white/[0.08] bg-[#0a0a0a] p-6 space-y-6 text-xs"
      >
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="sm:col-span-2">
            <label className="block text-[#b6b5b5] mb-1.5">Workspace name</label>
            <input
              type="text"
              required
              value={workspaceName}
              onChange={(e) => setWorkspaceName(e.target.value)}
              className="h-10 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3.5 text-sm text-[#fafafa]"
            />
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">Default provider</label>
            <select
              value={defaultProvider}
              onChange={(e) => {
                const nextP = e.target.value;
                setDefaultProvider(nextP);
                const firstM = models.find((m) => m.provider_key === nextP);
                if (firstM) setDefaultModel(firstM.model_id);
              }}
              className="h-10 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 text-[#fafafa]"
            >
              {providers.map((p) => (
                <option key={p.provider_key} value={p.provider_key}>
                  {p.display_name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">Default model</label>
            <select
              value={defaultModel}
              onChange={(e) => setDefaultModel(e.target.value)}
              className="h-10 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
            >
              {providerModels.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name} ({m.model_id})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">
              Default temperature ({defaultTemp.toFixed(2)})
            </label>
            <input
              type="range"
              min={0}
              max={2}
              step={0.05}
              value={defaultTemp}
              onChange={(e) => setDefaultTemp(parseFloat(e.target.value))}
              className="w-full accent-white"
            />
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">
              Default max output tokens
            </label>
            <input
              type="number"
              min={64}
              max={65536}
              value={defaultMaxTokens}
              onChange={(e) => setDefaultMaxTokens(Number(e.target.value))}
              className="h-10 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
            />
          </div>

          <div className="sm:col-span-2">
            <label className="block text-[#b6b5b5] mb-1.5">
              Default system instruction
            </label>
            <textarea
              rows={3}
              value={defaultSysPrompt}
              onChange={(e) => setDefaultSysPrompt(e.target.value)}
              placeholder="Applied to newly created conversations unless overridden..."
              className="w-full rounded-xl border border-white/[0.12] bg-[#050505] p-3 text-[#fafafa] placeholder-[#666666]"
            />
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">
              Context window budget ratio ({Math.round(contextRatio * 100)}%)
            </label>
            <input
              type="range"
              min={0.4}
              max={0.95}
              step={0.05}
              value={contextRatio}
              onChange={(e) => setContextRatio(parseFloat(e.target.value))}
              className="w-full accent-white"
            />
          </div>

          <div>
            <label className="block text-[#b6b5b5] mb-1.5">
              Background health-check interval (seconds)
            </label>
            <input
              type="number"
              min={30}
              max={3600}
              value={monitorInterval}
              onChange={(e) => setMonitorInterval(Number(e.target.value))}
              className="h-10 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-3 font-mono-tabular text-[#fafafa]"
            />
          </div>
        </div>

        <div className="space-y-3 border-t border-white/[0.08] pt-4">
          <label className="flex items-center gap-2.5 text-[#d4d4d4] cursor-pointer">
            <input
              type="checkbox"
              checked={autoMonitor}
              onChange={(e) => setAutoMonitor(e.target.checked)}
              className="accent-white"
            />
            <span>Enable scheduled background provider & model health checks</span>
          </label>

          <label className="flex items-center gap-2.5 text-[#d4d4d4] cursor-pointer">
            <input
              type="checkbox"
              checked={deepProbe}
              onChange={(e) => setDeepProbe(e.target.checked)}
              className="accent-white"
            />
            <span>
              Include 1-token deep inference probes during scheduled checks
            </span>
          </label>

          <label className="flex items-center gap-2.5 text-[#d4d4d4] cursor-pointer">
            <input
              type="checkbox"
              checked={notificationsEnabled}
              onChange={(e) => setNotificationsEnabled(e.target.checked)}
              className="accent-white"
            />
            <span>Enable live WebSocket status alerts in top bar</span>
          </label>
        </div>

        <div className="flex justify-end border-t border-white/[0.08] pt-4">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex h-10 items-center gap-2 rounded-full bg-[#ffffff] px-5 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8] disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            <span>{saving ? "Saving..." : "Save settings"}</span>
          </button>
        </div>
      </form>
    </div>
  );
};

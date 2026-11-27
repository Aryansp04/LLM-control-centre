import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  Copy,
  Download,
  Edit3,
  FileText,
  Image as ImageIcon,
  Loader2,
  Paperclip,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  SlidersHorizontal,
  Square,
  Trash2,
  X,
} from "lucide-react";
import {
  API_BASE_URL,
  ApiClientError,
  apiRequest,
  getStoredToken,
  streamChatCompletion,
} from "../api/client";
import { useApp } from "../context/AppContext";
import {
  AttachmentMeta,
  ChatMessage,
  ConversationDetail,
  ConversationSummary,
} from "../types";
import { MarkdownRenderer } from "../components/MarkdownRenderer";

export const ChatPage: React.FC = () => {
  const {
    providers,
    models,
    activeProvider,
    activeModel,
    setActiveSelection,
    refreshPlatformState,
  } = useApp();

  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [activeConvId, setActiveConvId] = useState<string | null>(null);
  const [activeConv, setActiveConv] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingConvList, setLoadingConvList] = useState<boolean>(true);
  const [loadingThread, setLoadingThread] = useState<boolean>(false);

  const [prompt, setPrompt] = useState<string>("");
  const [attachments, setAttachments] = useState<AttachmentMeta[]>([]);
  const [uploadingFile, setUploadingFile] = useState<boolean>(false);
  const [isStreaming, setIsStreaming] = useState<boolean>(false);
  const [activeStreamId, setActiveStreamId] = useState<string | null>(null);
  const [chatError, setChatError] = useState<string | null>(null);
  const [copiedMsgId, setCopiedMsgId] = useState<string | null>(null);

  const [paramsOpen, setParamsOpen] = useState<boolean>(false);
  const [systemInstruction, setSystemInstruction] = useState<string>("");
  const [temperature, setTemperature] = useState<number>(0.7);
  const [maxTokens, setMaxTokens] = useState<number>(4096);

  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState<string>("");
  const [mobileThreadsOpen, setMobileThreadsOpen] = useState<boolean>(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selectedModelObj = useMemo(
    () =>
      models.find(
        (m) => m.provider_key === activeProvider && m.model_id === activeModel
      ) || null,
    [models, activeProvider, activeModel]
  );

  const providerModels = useMemo(
    () => models.filter((m) => m.provider_key === activeProvider),
    [models, activeProvider]
  );

  const loadConversations = useCallback(async (q = "") => {
    try {
      const url = q.trim()
        ? `/api/conversations?search=${encodeURIComponent(q.trim())}`
        : "/api/conversations";
      const data = await apiRequest<{ items: ConversationSummary[] }>(url);
      setConversations(data.items);
    } catch {
      // ignore
    } finally {
      setLoadingConvList(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadConversations(searchQuery);
    }, 180);
    return () => window.clearTimeout(timer);
  }, [searchQuery, loadConversations]);

  const selectConversation = useCallback(
    async (convId: string) => {
      setActiveConvId(convId);
      setChatError(null);
      setLoadingThread(true);
      setMobileThreadsOpen(false);
      try {
        const detail = await apiRequest<ConversationDetail>(
          `/api/conversations/${convId}`
        );
        setActiveConv(detail);
        setMessages(detail.messages);
        setActiveSelection(detail.active_provider, detail.active_model);
        setSystemInstruction(detail.system_instruction || "");
        if (detail.temperature !== null) setTemperature(detail.temperature);
        if (detail.max_output_tokens !== null)
          setMaxTokens(detail.max_output_tokens);
      } catch (err) {
        setChatError(
          err instanceof ApiClientError ? err.message : "Failed to load conversation"
        );
      } finally {
        setLoadingThread(false);
      }
    },
    [setActiveSelection]
  );

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const handleNewChat = () => {
    setActiveConvId(null);
    setActiveConv(null);
    setMessages([]);
    setPrompt("");
    setAttachments([]);
    setChatError(null);
    setMobileThreadsOpen(false);
  };

  const handleProviderChange = (newProvKey: string) => {
    const firstModel = models.find((m) => m.provider_key === newProvKey);
    if (firstModel) {
      setActiveSelection(newProvKey, firstModel.model_id);
    } else {
      setActiveSelection(newProvKey, "");
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setChatError(null);
    setUploadingFile(true);
    try {
      for (const file of Array.from(files).slice(0, 5 - attachments.length)) {
        const form = new FormData();
        form.append("file", file);
        const validated = await apiRequest<AttachmentMeta>(
          "/api/chat/attachments/validate",
          {
            method: "POST",
            body: form,
          }
        );
        setAttachments((prev) => [...prev, validated]);
      }
    } catch (err) {
      setChatError(
        err instanceof ApiClientError
          ? err.message
          : "File attachment validation failed."
      );
    } finally {
      setUploadingFile(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const executeStream = async (options?: {
    regenerateFromId?: string;
    overridePrompt?: string;
    overrideProvider?: string;
    overrideModel?: string;
  }) => {
    const useProvider = options?.overrideProvider || activeProvider;
    const useModel = options?.overrideModel || activeModel;
    if (options?.overrideProvider && options?.overrideModel) {
      setActiveSelection(options.overrideProvider, options.overrideModel);
    }
    const textToSend = options?.overridePrompt ?? prompt;
    if (
      !options?.regenerateFromId &&
      !textToSend.trim() &&
      attachments.length === 0
    ) {
      return;
    }

    setChatError(null);
    setIsStreaming(true);

    const submittedAttachments = options?.regenerateFromId ? [] : [...attachments];
    if (!options?.regenerateFromId) {
      setPrompt("");
      setAttachments([]);
    }

    const optimisticUserId = `temp-user-${Date.now()}`;
    const optimisticAssistantId = `temp-asst-${Date.now()}`;
    const nowIso = new Date().toISOString();

    if (!options?.regenerateFromId) {
      const optimisticUser: ChatMessage = {
        id: optimisticUserId,
        conversation_id: activeConvId || "pending",
        role: "user",
        content: textToSend,
        provider_key: useProvider,
        requested_model: useModel,
        actual_model_used: null,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        latency_ms: null,
        ttft_ms: null,
        tokens_per_second: null,
        estimated_cost_usd: null,
        status: "completed",
        error_message: null,
        attachments: submittedAttachments,
        metadata: {},
        created_at: nowIso,
      };
      const optimisticAssistant: ChatMessage = {
        id: optimisticAssistantId,
        conversation_id: activeConvId || "pending",
        role: "assistant",
        content: "",
        provider_key: useProvider,
        requested_model: useModel,
        actual_model_used: useModel,
        input_tokens: 0,
        output_tokens: 0,
        total_tokens: 0,
        latency_ms: null,
        ttft_ms: null,
        tokens_per_second: null,
        estimated_cost_usd: null,
        status: "streaming",
        error_message: null,
        attachments: [],
        metadata: {},
        created_at: nowIso,
      };
      setMessages((prev) => [...prev, optimisticUser, optimisticAssistant]);
    } else {
      setMessages((prev) => {
        const idx = prev.findIndex((m) => m.id === options.regenerateFromId);
        const base =
          idx === -1
            ? prev
            : prev[idx].role === "assistant"
            ? prev.slice(0, idx)
            : prev.slice(0, idx + 1);
        return [
          ...base,
          {
            id: optimisticAssistantId,
            conversation_id: activeConvId || "pending",
            role: "assistant",
            content: "",
            provider_key: useProvider,
            requested_model: useModel,
            actual_model_used: useModel,
            input_tokens: 0,
            output_tokens: 0,
            total_tokens: 0,
            latency_ms: null,
            ttft_ms: null,
            tokens_per_second: null,
            estimated_cost_usd: null,
            status: "streaming",
            error_message: null,
            attachments: [],
            metadata: {},
            created_at: nowIso,
          },
        ];
      });
    }

    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    let resolvedConvId = activeConvId;

    try {
      await streamChatCompletion(
        {
          conversation_id: activeConvId,
          provider_key: useProvider,
          model_id: useModel,
          message: options?.regenerateFromId ? "" : textToSend,
          system_instruction: systemInstruction.trim() || null,
          temperature: selectedModelObj?.supports_temperature ? temperature : null,
          max_output_tokens: maxTokens,
          attachments: submittedAttachments.map((a) => ({
            filename: a.filename,
            content_type: a.mime_type,
            base64_content: a.base64_content || "",
          })),
          regenerate_from_message_id: options?.regenerateFromId || null,
        },
        {
          onStart: (startInfo) => {
            resolvedConvId = startInfo.conversation_id;
            setActiveConvId(startInfo.conversation_id);
            setActiveStreamId(startInfo.stream_id);
            setMessages((prev) =>
              prev.map((m) => {
                if (m.id === optimisticUserId) {
                  return {
                    ...m,
                    id: startInfo.user_message_id,
                    conversation_id: startInfo.conversation_id,
                  };
                }
                if (m.id === optimisticAssistantId) {
                  return {
                    ...m,
                    id: startInfo.assistant_message_id,
                    conversation_id: startInfo.conversation_id,
                  };
                }
                return m;
              })
            );
          },
          onToken: (delta, actualMod) => {
            setMessages((prev) =>
              prev.map((m, idx) =>
                idx === prev.length - 1 && m.role === "assistant"
                  ? {
                      ...m,
                      content: m.content + delta,
                      actual_model_used: actualMod || m.actual_model_used,
                    }
                  : m
              )
            );
          },
          onEnd: (telemetry) => {
            setMessages((prev) =>
              prev.map((m, idx) =>
                idx === prev.length - 1 && m.role === "assistant"
                  ? {
                      ...m,
                      status: "completed",
                      actual_model_used:
                        (telemetry.actual_model_used as string) || m.actual_model_used,
                      input_tokens: Number(telemetry.input_tokens || 0),
                      output_tokens: Number(telemetry.output_tokens || 0),
                      total_tokens: Number(telemetry.total_tokens || 0),
                      latency_ms: Number(telemetry.latency_ms || 0),
                      ttft_ms:
                        telemetry.ttft_ms !== null
                          ? Number(telemetry.ttft_ms)
                          : null,
                      tokens_per_second:
                        telemetry.tokens_per_second !== null
                          ? Number(telemetry.tokens_per_second)
                          : null,
                      estimated_cost_usd:
                        telemetry.estimated_cost_usd !== null
                          ? Number(telemetry.estimated_cost_usd)
                          : null,
                    }
                  : m
              )
            );
          },
          onCancelled: () => {
            setMessages((prev) =>
              prev.map((m, idx) =>
                idx === prev.length - 1 && m.role === "assistant"
                  ? { ...m, status: "cancelled" }
                  : m
              )
            );
          },
          onError: (errEvt) => {
            setChatError(errEvt.message);
            setMessages((prev) =>
              prev.map((m, idx) =>
                idx === prev.length - 1 && m.role === "assistant"
                  ? {
                      ...m,
                      status: "failed",
                      error_message: errEvt.message,
                    }
                  : m
              )
            );
          },
        },
        abortController.signal
      );

      if (resolvedConvId) {
        const refreshed = await apiRequest<ConversationDetail>(
          `/api/conversations/${resolvedConvId}`
        );
        setActiveConv(refreshed);
        setMessages(refreshed.messages);
      }
      await Promise.all([loadConversations(searchQuery), refreshPlatformState()]);
    } catch (err) {
      if ((err as Error)?.name === "AbortError") {
        setMessages((prev) =>
          prev.map((m, idx) =>
            idx === prev.length - 1 && m.role === "assistant"
              ? { ...m, status: "cancelled" }
              : m
          )
        );
      } else {
        const msg =
          err instanceof ApiClientError
            ? err.message
            : "Streaming request failed.";
        setChatError(msg);
        setMessages((prev) =>
          prev.map((m, idx) =>
            idx === prev.length - 1 && m.role === "assistant"
              ? { ...m, status: "failed", error_message: msg }
              : m
          )
        );
      }
    } finally {
      setIsStreaming(false);
      setActiveStreamId(null);
      abortControllerRef.current = null;
    }
  };

  const handleStopGeneration = async () => {
    if (activeStreamId) {
      try {
        await apiRequest("/api/chat/cancel", {
          method: "POST",
          body: JSON.stringify({ stream_id: activeStreamId }),
        });
      } catch {
        // fallback to client abort
      }
    }
    abortControllerRef.current?.abort();
  };

  const handleRenameSave = async (convId: string) => {
    if (!renameDraft.trim()) {
      setRenamingId(null);
      return;
    }
    await apiRequest(`/api/conversations/${convId}`, {
      method: "PATCH",
      body: JSON.stringify({ title: renameDraft.trim() }),
    });
    setRenamingId(null);
    await loadConversations(searchQuery);
    if (activeConvId === convId && activeConv) {
      setActiveConv({ ...activeConv, title: renameDraft.trim() });
    }
  };

  const handleDeleteConversation = async (convId: string) => {
    await apiRequest(`/api/conversations/${convId}`, { method: "DELETE" });
    if (activeConvId === convId) {
      handleNewChat();
    }
    await loadConversations(searchQuery);
  };

  const handleExport = async (format: "markdown" | "json") => {
    if (!activeConvId) return;
    const token = getStoredToken();
    const resp = await fetch(
      `${API_BASE_URL}/api/conversations/${activeConvId}/export?format=${format}`,
      {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      }
    );
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `conversation-${activeConvId.slice(0, 8)}.${
      format === "markdown" ? "md" : "json"
    }`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleCopyMessage = async (msg: ChatMessage) => {
    await navigator.clipboard.writeText(msg.content);
    setCopiedMsgId(msg.id);
    window.setTimeout(() => setCopiedMsgId(null), 1800);
  };

  const renderThreadList = () => (
    <div className="flex h-full flex-col bg-[#080808]">
      <div className="p-3.5 border-b border-white/[0.08] space-y-2.5">
        <button
          type="button"
          onClick={handleNewChat}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
        >
          <Plus className="h-4 w-4" />
          <span>New chat</span>
        </button>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-3.5 w-3.5 text-[#8b8a8a]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search conversations"
            aria-label="Search conversations"
            className="h-8 w-full rounded-full border border-white/[0.12] bg-[#050505] pl-8 pr-3 text-xs text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
          />
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {loadingConvList ? (
          <div className="p-4 text-xs text-[#8b8a8a]">Loading history...</div>
        ) : conversations.length === 0 ? (
          <div className="p-6 text-center text-xs text-[#8b8a8a]">
            {searchQuery ? "No matching threads" : "No conversations yet"}
          </div>
        ) : (
          conversations.map((c) => {
            const isSelected = c.id === activeConvId;
            return (
              <div
                key={c.id}
                className={`group rounded-xl border px-3 py-2 transition-colors ${
                  isSelected
                    ? "border-white/[0.14] bg-white/[0.06] text-[#fafafa]"
                    : "border-transparent text-[#a7a6a6] hover:bg-white/[0.03] hover:text-[#fafafa]"
                }`}
              >
                {renamingId === c.id ? (
                  <div className="flex items-center gap-1">
                    <input
                      type="text"
                      autoFocus
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") void handleRenameSave(c.id);
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="h-7 flex-1 rounded-lg border border-white/40 bg-[#050505] px-2 text-xs text-[#fafafa] focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => void handleRenameSave(c.id)}
                      className="p-1 text-[#fafafa]"
                    >
                      <Check className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => void selectConversation(c.id)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <div className="truncate text-xs font-medium">{c.title}</div>
                      <div className="mt-1 flex items-center gap-1.5 text-[11px] font-mono-tabular text-[#8b8a8a]">
                        <span className="truncate">{c.active_model}</span>
                        <span>·</span>
                        <span>{c.total_tokens.toLocaleString()} tok</span>
                      </div>
                    </button>
                    <div className="hidden group-hover:flex items-center gap-1 shrink-0">
                      <button
                        type="button"
                        aria-label="Rename conversation"
                        onClick={() => {
                          setRenamingId(c.id);
                          setRenameDraft(c.title);
                        }}
                        className="rounded p-1 text-[#a7a6a6] hover:bg-white/10 hover:text-[#fafafa]"
                      >
                        <Edit3 className="h-3 w-3" />
                      </button>
                      <button
                        type="button"
                        aria-label="Delete conversation"
                        onClick={() => void handleDeleteConversation(c.id)}
                        className="rounded p-1 text-[#a7a6a6] hover:bg-[#ef4444]/15 hover:text-[#fca5a5]"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );

  const convTokens =
    activeConv?.total_tokens ??
    messages.reduce((acc, m) => acc + (m.total_tokens || 0), 0);
  const convCost = activeConv?.total_estimated_cost_usd ?? 0;

  return (
    <div className="flex h-full w-full overflow-hidden bg-[#050505]">
      <div className="hidden md:block w-72 shrink-0 border-r border-white/[0.08]">
        {renderThreadList()}
      </div>

      {mobileThreadsOpen && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div
            className="fixed inset-0 bg-black/80"
            onClick={() => setMobileThreadsOpen(false)}
          />
          <div className="relative z-10 w-72 border-r border-white/10 bg-[#080808]">
            {renderThreadList()}
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col bg-[#050505]">
        {/* Chat Control Header */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.08] bg-[#080808] px-4 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setMobileThreadsOpen(true)}
              className="rounded-full border border-white/[0.14] bg-white/[0.04] px-3 py-1.5 text-xs text-[#fafafa] md:hidden"
            >
              History
            </button>

            <select
              aria-label="Select LLM provider"
              value={activeProvider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="h-8 rounded-full border border-white/[0.12] bg-[#0d0d0d] px-3 text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
            >
              {providers.map((p) => (
                <option key={p.provider_key} value={p.provider_key}>
                  {p.display_name}
                  {!p.has_api_key ? " (Unconfigured)" : ""}
                </option>
              ))}
            </select>

            <select
              aria-label="Select model"
              value={activeModel}
              onChange={(e) => setActiveSelection(activeProvider, e.target.value)}
              className="h-8 rounded-full border border-white/[0.12] bg-[#0d0d0d] px-3 text-xs font-mono-tabular text-[#fafafa] focus:border-white/40 focus:outline-none"
            >
              {providerModels.map((m) => (
                <option key={m.model_id} value={m.model_id}>
                  {m.display_name} ({Math.round(m.context_window / 1000)}k ctx)
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={() => setParamsOpen((v) => !v)}
              className={`inline-flex h-8 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors ${
                paramsOpen
                  ? "border-white bg-white text-[#050505] font-medium"
                  : "border-white/[0.12] bg-white/[0.04] text-[#b6b5b5] hover:text-[#fafafa]"
              }`}
            >
              <SlidersHorizontal className="h-3.5 w-3.5" />
              <span>Parameters</span>
            </button>
          </div>

          <div className="flex items-center gap-2 text-xs">
            {(() => {
              const activeProvObj = providers.find(
                (p) => p.provider_key === activeProvider
              );
              const q = activeProvObj?.quota;
              if (!q) return null;
              return (
                <div
                  title={`Resets to 100% every ${q.window_hours} hours`}
                  className="hidden lg:flex items-center gap-2 rounded-full border border-white/[0.1] bg-white/[0.03] px-3 py-1 font-mono-tabular text-[#a7a6a6]"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-[#22c55e]" />
                  <span className="text-[#fafafa]">
                    {q.remaining_pct.toFixed(1)}%
                  </span>
                  <span>({q.window_hours}h quota)</span>
                </div>
              );
            })()}
            <div className="rounded-full border border-white/[0.1] bg-white/[0.03] px-3 py-1 font-mono-tabular text-[#a7a6a6]">
              <span>{convTokens.toLocaleString()} tokens</span>
              {convCost > 0 && (
                <span className="ml-2 text-[#fafafa]">
                  ~${convCost.toFixed(5)}
                </span>
              )}
            </div>

            {activeConvId && (
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  title="Export Markdown"
                  onClick={() => void handleExport("markdown")}
                  className="inline-flex h-8 items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.04] px-3 text-xs text-[#b6b5b5] hover:text-[#fafafa]"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">MD</span>
                </button>
                <button
                  type="button"
                  title="Export JSON"
                  onClick={() => void handleExport("json")}
                  className="inline-flex h-8 items-center gap-1 rounded-full border border-white/[0.12] bg-white/[0.04] px-3 text-xs text-[#b6b5b5] hover:text-[#fafafa]"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">JSON</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Parameters Drawer */}
        {paramsOpen && (
          <div className="border-b border-white/[0.08] bg-[#0a0a0a] px-4 py-3.5 grid grid-cols-1 md:grid-cols-12 gap-4 text-xs">
            <div className="md:col-span-7">
              <label className="block text-[#b6b5b5] mb-1">
                System instruction
              </label>
              <textarea
                rows={2}
                value={systemInstruction}
                onChange={(e) => setSystemInstruction(e.target.value)}
                placeholder="Optional system-level instructions applied to this conversation..."
                className="w-full rounded-xl border border-white/[0.12] bg-[#050505] p-2.5 text-xs text-[#fafafa] placeholder-[#666666] focus:border-white/40 focus:outline-none"
              />
            </div>

            <div className="md:col-span-5 grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[#b6b5b5] mb-1">
                  {selectedModelObj?.supports_temperature === false
                    ? "Temperature (Fixed)"
                    : `Temperature: ${temperature.toFixed(2)}`}
                </label>
                <input
                  type="range"
                  min={0}
                  max={activeProvider === "anthropic" ? 1 : 2}
                  step={0.05}
                  disabled={selectedModelObj?.supports_temperature === false}
                  value={temperature}
                  onChange={(e) => setTemperature(parseFloat(e.target.value))}
                  className="w-full accent-white disabled:opacity-40"
                />
                <div className="mt-1 text-[11px] text-[#8b8a8a]">
                  {selectedModelObj?.supports_temperature === false
                    ? "Not supported by reasoning model"
                    : activeProvider === "anthropic"
                    ? "Range 0.0 – 1.0"
                    : "Range 0.0 – 2.0"}
                </div>
              </div>

              <div>
                <label className="block text-[#b6b5b5] mb-1">
                  Max output tokens
                </label>
                <input
                  type="number"
                  min={32}
                  max={selectedModelObj?.max_output_tokens || 65536}
                  value={maxTokens}
                  onChange={(e) =>
                    setMaxTokens(Math.max(32, Number(e.target.value) || 2048))
                  }
                  className="h-8 w-full rounded-xl border border-white/[0.12] bg-[#050505] px-2.5 font-mono-tabular text-xs text-[#fafafa] focus:border-white/40 focus:outline-none"
                />
              </div>
            </div>
          </div>
        )}

        {/* Messages Viewport */}
        <div className="flex-1 overflow-y-auto px-4 py-6 sm:px-6">
          <div className="mx-auto max-w-3xl space-y-6">
            {loadingThread ? (
              <div className="flex items-center justify-center py-20 text-xs text-[#a7a6a6] gap-2">
                <Loader2 className="h-4 w-4 animate-spin text-[#fafafa]" />
                <span>Loading conversation context...</span>
              </div>
            ) : messages.length === 0 ? (
              <div className="my-12 rounded-3xl border border-white/[0.08] bg-[#0a0a0a] p-9 text-center">
                <h2 className="text-xl font-normal tracking-tight text-[#fafafa]">
                  The Next Layer of Intelligence
                </h2>
                <p className="mt-2.5 text-xs text-[#a7a6a6] max-w-md mx-auto leading-relaxed">
                  Select OpenAI, Google Gemini, or Anthropic Claude above. Switch
                  models mid-conversation without losing context, attach files,
                  and stream live telemetry on every response.
                </p>
                {selectedModelObj && (
                  <div className="mt-5 inline-flex flex-wrap items-center justify-center gap-2 text-[11px] font-mono-tabular text-[#a7a6a6]">
                    <span className="rounded-full border border-white/[0.12] bg-[#050505] px-3 py-1">
                      {selectedModelObj.provider_name} / {selectedModelObj.display_name}
                    </span>
                    <span className="rounded-full border border-white/[0.12] bg-[#050505] px-3 py-1">
                      {selectedModelObj.context_window.toLocaleString()} ctx
                    </span>
                  </div>
                )}
              </div>
            ) : (
              messages.map((msg) => {
                const isUser = msg.role === "user";
                return (
                  <div
                    key={msg.id}
                    className={`flex flex-col ${
                      isUser ? "items-end" : "items-start"
                    }`}
                  >
                    <div className="mb-1.5 flex items-center gap-2 text-[11px] text-[#a7a6a6]">
                      <span className="font-medium text-[#fafafa]">
                        {isUser
                          ? "You"
                          : msg.actual_model_used ||
                            msg.requested_model ||
                            "Assistant"}
                      </span>
                      {!isUser && msg.provider_key && (
                        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-0.5 text-[10px] capitalize">
                          {msg.provider_key}
                        </span>
                      )}
                      <span className="font-mono-tabular text-[#8b8a8a]">
                        {new Date(msg.created_at).toLocaleTimeString([], {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </span>
                    </div>

                    <div
                      className={`max-w-full sm:max-w-[90%] rounded-2xl border px-4 py-3 ${
                        isUser
                          ? "border-white/[0.18] bg-white/[0.06] text-[#fafafa]"
                          : msg.status === "failed"
                          ? "border-[#ef4444]/35 bg-[#ef4444]/10 text-[#fca5a5]"
                          : "border-white/[0.08] bg-[#0a0a0a] text-[#fafafa]"
                      }`}
                    >
                      {msg.attachments && msg.attachments.length > 0 && (
                        <div className="mb-2.5 flex flex-wrap gap-2">
                          {msg.attachments.map((att, idx) => (
                            <div
                              key={idx}
                              className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-[#050505] px-3 py-1 text-xs text-[#a7a6a6]"
                            >
                              {att.kind === "image" ? (
                                <ImageIcon className="h-3.5 w-3.5 text-[#fafafa]" />
                              ) : (
                                <FileText className="h-3.5 w-3.5 text-[#fafafa]" />
                              )}
                              <span className="truncate max-w-[160px]">
                                {att.filename}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}

                      {msg.status === "streaming" && !msg.content ? (
                        <div className="flex items-center gap-2 py-1 text-xs text-[#a7a6a6]">
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-[#fafafa]" />
                          <span>Generating response...</span>
                        </div>
                      ) : msg.status === "failed" ? (
                        <div className="space-y-2.5 text-xs">
                          <div className="flex items-start gap-2">
                            <AlertCircle className="h-4 w-4 shrink-0 text-[#ef4444] mt-0.5" />
                            <span>
                              {msg.error_message || "Provider request failed."}
                            </span>
                          </div>
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              disabled={isStreaming}
                              onClick={() =>
                                void executeStream({ regenerateFromId: msg.id })
                              }
                              className="inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-white/[0.04] px-3 py-1 text-xs text-[#fafafa] hover:bg-white/10"
                            >
                              <RotateCcw className="h-3 w-3" />
                              <span>Retry</span>
                            </button>
                            {(() => {
                              const fallbackModel = models.find(
                                (m) =>
                                  m.has_credentials &&
                                  m.provider_key !== msg.provider_key
                              );
                              if (!fallbackModel) return null;
                              return (
                                <button
                                  type="button"
                                  disabled={isStreaming}
                                  onClick={() =>
                                    void executeStream({
                                      regenerateFromId: msg.id,
                                      overrideProvider: fallbackModel.provider_key,
                                      overrideModel: fallbackModel.model_id,
                                    })
                                  }
                                  className="inline-flex items-center gap-1.5 rounded-full bg-[#ffffff] px-3 py-1 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8]"
                                >
                                  <RefreshCw className="h-3 w-3" />
                                  <span>
                                    Switch to {fallbackModel.display_name}
                                  </span>
                                </button>
                              );
                            })()}
                          </div>
                        </div>
                      ) : isUser ? (
                        <div className="whitespace-pre-wrap text-sm leading-relaxed">
                          {msg.content}
                        </div>
                      ) : (
                        <MarkdownRenderer content={msg.content} />
                      )}
                    </div>

                    {!isUser && msg.status !== "streaming" && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-[11px] text-[#8b8a8a]">
                        {msg.total_tokens > 0 && (
                          <span className="font-mono-tabular">
                            {msg.total_tokens} tok ({msg.input_tokens} in /{" "}
                            {msg.output_tokens} out)
                          </span>
                        )}
                        {msg.latency_ms !== null && (
                          <span className="font-mono-tabular">
                            {msg.latency_ms.toFixed(0)} ms
                            {msg.ttft_ms !== null
                              ? ` · TTFT ${msg.ttft_ms.toFixed(0)} ms`
                              : ""}
                            {msg.tokens_per_second !== null
                              ? ` · ${msg.tokens_per_second.toFixed(1)} tok/s`
                              : ""}
                          </span>
                        )}

                        <button
                          type="button"
                          onClick={() => void handleCopyMessage(msg)}
                          className="inline-flex items-center gap-1 text-[#a7a6a6] hover:text-[#fafafa]"
                        >
                          {copiedMsgId === msg.id ? (
                            <>
                              <Check className="h-3 w-3 text-[#22c55e]" />
                              <span>Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy className="h-3 w-3" />
                              <span>Copy</span>
                            </>
                          )}
                        </button>

                        <button
                          type="button"
                          disabled={isStreaming}
                          onClick={() =>
                            void executeStream({ regenerateFromId: msg.id })
                          }
                          className="inline-flex items-center gap-1 text-[#a7a6a6] hover:text-[#fafafa] disabled:opacity-40"
                        >
                          <RefreshCw className="h-3 w-3" />
                          <span>Regenerate</span>
                        </button>
                      </div>
                    )}
                  </div>
                );
              })
            )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {chatError && (
          <div className="mx-auto w-full max-w-3xl px-4 pb-2">
            <div className="flex items-center justify-between gap-2 rounded-xl border border-[#ef4444]/30 bg-[#ef4444]/10 px-3.5 py-2 text-xs text-[#fca5a5]">
              <span>{chatError}</span>
              <button
                type="button"
                onClick={() => setChatError(null)}
                className="text-[#fca5a5] hover:text-white"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        {/* Composer */}
        <div className="border-t border-white/[0.08] bg-[#080808] p-4">
          <div className="mx-auto max-w-3xl">
            {attachments.length > 0 && (
              <div className="mb-2.5 flex flex-wrap gap-2">
                {attachments.map((att, idx) => (
                  <div
                    key={idx}
                    className="inline-flex items-center gap-2 rounded-full border border-white/12 bg-[#0d0d0d] px-3 py-1 text-xs text-[#fafafa]"
                  >
                    <span className="truncate max-w-[160px]">{att.filename}</span>
                    <span className="font-mono-tabular text-[10px] text-[#8b8a8a]">
                      {(att.size_bytes / 1024).toFixed(1)} KB
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setAttachments((prev) => prev.filter((_, i) => i !== idx))
                      }
                      className="text-[#8b8a8a] hover:text-[#fca5a5]"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-end gap-2 rounded-2xl border border-white/[0.12] bg-[#0d0d0d] p-2.5 focus-within:border-white/35">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={handleFileChange}
                accept=".txt,.md,.csv,.json,.yaml,.yml,.py,.js,.ts,.tsx,.sql,.pdf,.png,.jpg,.jpeg,.webp,.gif"
                className="hidden"
              />
              <button
                type="button"
                disabled={uploadingFile || isStreaming || attachments.length >= 5}
                onClick={() => fileInputRef.current?.click()}
                title="Attach text, code, PDF, or image file"
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[#a7a6a6] hover:bg-white/[0.08] hover:text-[#fafafa] disabled:opacity-40"
              >
                {uploadingFile ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Paperclip className="h-4 w-4" strokeWidth={1.7} />
                )}
              </button>

              <textarea
                rows={2}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    if (!isStreaming) void executeStream();
                  }
                }}
                placeholder={`Message ${selectedModelObj?.display_name || activeModel}... (Enter to send, Shift+Enter for newline)`}
                className="max-h-40 flex-1 resize-none bg-transparent py-1.5 text-sm text-[#fafafa] placeholder-[#666666] focus:outline-none"
              />

              {isStreaming ? (
                <button
                  type="button"
                  onClick={() => void handleStopGeneration()}
                  className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-[#ef4444] px-4 text-xs font-medium text-white hover:bg-[#dc2626]"
                >
                  <Square className="h-3.5 w-3.5 fill-current" />
                  <span>Stop</span>
                </button>
              ) : (
                <button
                  type="button"
                  disabled={!prompt.trim() && attachments.length === 0}
                  onClick={() => void executeStream()}
                  className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full bg-[#ffffff] px-4 text-xs font-medium text-[#050505] hover:bg-[#e8e8e8] disabled:opacity-40"
                >
                  <span>Send</span>
                  <Send className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

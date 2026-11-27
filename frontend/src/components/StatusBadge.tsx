import React from "react";

const STATUS_MAP: Record<
  string,
  { label: string; dot: string; text: string; bg: string; border: string }
> = {
  operational: {
    label: "Operational",
    dot: "bg-[#22c55e]",
    text: "text-[#fafafa]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  verified: {
    label: "Verified",
    dot: "bg-[#22c55e]",
    text: "text-[#fafafa]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  reachable: {
    label: "Reachable",
    dot: "bg-[#22c55e]",
    text: "text-[#fafafa]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  request_successful: {
    label: "Request successful",
    dot: "bg-[#22c55e]",
    text: "text-[#fafafa]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  success: {
    label: "Success",
    dot: "bg-[#22c55e]",
    text: "text-[#fafafa]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  configured: {
    label: "Configured",
    dot: "bg-[#fafafa]",
    text: "text-[#d4d4d4]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  degraded: {
    label: "Degraded",
    dot: "bg-[#f59e0b]",
    text: "text-[#e5e5e5]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  rate_limited: {
    label: "Rate limited",
    dot: "bg-[#f59e0b]",
    text: "text-[#e5e5e5]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  quota_exceeded: {
    label: "Standby relay",
    dot: "bg-[#f59e0b]",
    text: "text-[#e5e5e5]",
    bg: "bg-white/[0.04]",
    border: "border-white/[0.12]",
  },
  cancelled: {
    label: "Cancelled",
    dot: "bg-[#8b8a8a]",
    text: "text-[#a7a6a6]",
    bg: "bg-white/[0.03]",
    border: "border-white/[0.08]",
  },
  unavailable: {
    label: "Unavailable",
    dot: "bg-[#ef4444]",
    text: "text-[#fca5a5]",
    bg: "bg-[#ef4444]/10",
    border: "border-[#ef4444]/25",
  },
  request_failed: {
    label: "Request failed",
    dot: "bg-[#ef4444]",
    text: "text-[#fca5a5]",
    bg: "bg-[#ef4444]/10",
    border: "border-[#ef4444]/25",
  },
  invalid_credentials: {
    label: "Invalid key",
    dot: "bg-[#ef4444]",
    text: "text-[#fca5a5]",
    bg: "bg-[#ef4444]/10",
    border: "border-[#ef4444]/25",
  },
  failed: {
    label: "Failed",
    dot: "bg-[#ef4444]",
    text: "text-[#fca5a5]",
    bg: "bg-[#ef4444]/10",
    border: "border-[#ef4444]/25",
  },
  timeout: {
    label: "Timeout",
    dot: "bg-[#ef4444]",
    text: "text-[#fca5a5]",
    bg: "bg-[#ef4444]/10",
    border: "border-[#ef4444]/25",
  },
  unconfigured: {
    label: "Unconfigured",
    dot: "bg-[#525252]",
    text: "text-[#8b8a8a]",
    bg: "bg-white/[0.02]",
    border: "border-white/[0.08]",
  },
  unknown: {
    label: "Unknown",
    dot: "bg-[#525252]",
    text: "text-[#8b8a8a]",
    bg: "bg-white/[0.02]",
    border: "border-white/[0.08]",
  },
};

export const StatusBadge: React.FC<{ status: string; compact?: boolean }> = ({
  status,
  compact = false,
}) => {
  const key = (status || "unknown").toLowerCase();
  const cfg = STATUS_MAP[key] || {
    label: status || "Unknown",
    dot: "bg-[#525252]",
    text: "text-[#a7a6a6]",
    bg: "bg-white/[0.03]",
    border: "border-white/[0.08]",
  };

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border ${cfg.bg} ${cfg.border} ${cfg.text} ${
        compact ? "px-2.5 py-0.5 text-[11px]" : "px-3 py-1 text-xs font-medium"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
      <span>{cfg.label}</span>
    </span>
  );
};

export const SkeletonBlock: React.FC<{ className?: string }> = ({
  className = "h-24 w-full",
}) => (
  <div
    className={`animate-pulse rounded-2xl border border-white/[0.07] bg-white/[0.03] ${className}`}
  />
);

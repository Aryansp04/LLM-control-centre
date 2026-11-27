import React, { useState } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Bell,
  Boxes,
  ChevronDown,
  Cpu,
  FileText,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { BrandMark } from "./BrandMark";

const NAV_ITEMS = [
  { to: "/overview", label: "Overview", icon: LayoutDashboard },
  { to: "/chat", label: "AI Chat", icon: MessageSquare },
  { to: "/models", label: "Models", icon: Cpu },
  { to: "/providers", label: "Providers", icon: Boxes },
  { to: "/monitoring", label: "Live Monitoring", icon: Activity },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/logs", label: "API Logs", icon: FileText },
  { to: "/settings", label: "Settings", icon: Settings },
];

export const AppShell: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const {
    user,
    wsState,
    models,
    settings,
    liveEvents,
    activeProvider,
    activeModel,
    setActiveSelection,
    logout,
    markAllEventsRead,
  } = useApp();

  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const unreadCount = liveEvents.filter((e) => e.is_read === false).length;

  const wsBadge = {
    connected: {
      dot: "bg-[#22c55e]",
      label: "Live stream connected",
      short: "Live",
      text: "text-[#fafafa]",
    },
    connecting: {
      dot: "bg-[#f59e0b]",
      label: "Connecting live socket",
      short: "Connecting",
      text: "text-[#a7a6a6]",
    },
    reconnecting: {
      dot: "bg-[#f59e0b]",
      label: "Reconnecting live socket",
      short: "Reconnecting",
      text: "text-[#a7a6a6]",
    },
    disconnected: {
      dot: "bg-[#ef4444]",
      label: "Live socket offline",
      short: "Offline",
      text: "text-[#fca5a5]",
    },
  }[wsState];

  const handleModelSwitch = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    const [prov, ...rest] = val.split("::");
    const mod = rest.join("::");
    if (prov && mod) {
      setActiveSelection(prov, mod);
    }
  };

  const renderNavLinks = (onClickItem?: () => void) => (
    <nav className="flex flex-col gap-1 px-3 py-4" aria-label="Main navigation">
      {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
        <NavLink
          key={to}
          to={to}
          onClick={onClickItem}
          className={({ isActive }) =>
            `group flex h-9 items-center gap-2.5 rounded-full px-3.5 text-sm transition-colors ${
              isActive
                ? "bg-white text-[#050505] font-medium"
                : "text-[#b6b5b5] hover:bg-white/[0.06] hover:text-[#fafafa]"
            }`
          }
        >
          <Icon className="h-4 w-4 shrink-0" strokeWidth={1.6} />
          <span className="truncate">{label}</span>
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[#050505] text-[#fafafa]">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:shrink-0 lg:flex-col border-r border-white/[0.08] bg-[#080808]">
        <div className="flex h-16 items-center justify-between border-b border-white/[0.08] px-5">
          <Link
            to="/"
            title="Return to Hero Stage"
            className="flex items-center gap-3 min-w-0 group"
          >
            <BrandMark className="h-7 w-[18px] shrink-0 transition-transform group-hover:scale-105" />
            <div className="min-w-0">
              <div className="truncate text-sm font-medium tracking-tight text-[#fafafa]">
                Control Center
              </div>
              <div className="truncate text-[11px] text-[#8b8a8a]">
                Next Layer Infrastructure
              </div>
            </div>
          </Link>
        </div>

        <div className="flex-1 overflow-y-auto">{renderNavLinks()}</div>

        <div className="border-t border-white/[0.08] p-4 space-y-2.5">
          <Link
            to="/"
            className="flex items-center justify-center gap-2 h-8 w-full rounded-full border border-white/[0.12] bg-white/[0.04] text-xs text-[#b6b5b5] hover:bg-white/[0.08] hover:text-[#fafafa] transition-colors"
          >
            <Sparkles className="h-3.5 w-3.5" strokeWidth={1.6} />
            <span>Hero Stage</span>
          </Link>
          <div className="rounded-2xl border border-white/[0.08] bg-white/[0.02] p-3">
            <div className="flex items-center justify-between text-xs">
              <span className="text-[#8b8a8a]">Telemetry bus</span>
              <span className={`inline-flex items-center gap-1.5 font-medium ${wsBadge.text}`}>
                <span className={`h-1.5 w-1.5 rounded-full ${wsBadge.dot}`} />
                {wsBadge.short}
              </span>
            </div>
            <div className="mt-1.5 truncate text-xs font-mono-tabular text-[#a7a6a6]">
              {activeProvider} / {activeModel}
            </div>
          </div>
        </div>
      </aside>

      {/* Mobile Drawer */}
      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div
            className="fixed inset-0 bg-black/80 backdrop-blur-sm"
            onClick={() => setMobileNavOpen(false)}
          />
          <aside className="relative z-10 flex w-64 flex-col bg-[#080808] border-r border-white/10">
            <div className="flex h-16 items-center justify-between border-b border-white/[0.08] px-4">
              <Link
                to="/"
                onClick={() => setMobileNavOpen(false)}
                className="flex items-center gap-2.5"
              >
                <BrandMark className="h-6 w-4" />
                <span className="text-sm font-medium text-[#fafafa]">
                  Control Center
                </span>
              </Link>
              <button
                type="button"
                aria-label="Close navigation"
                onClick={() => setMobileNavOpen(false)}
                className="rounded-full p-1.5 text-[#a7a6a6] hover:bg-white/[0.08] hover:text-[#fafafa]"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {renderNavLinks(() => setMobileNavOpen(false))}
            </div>
          </aside>
        </div>
      )}

      {/* Main Content Shell */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-[#050505]">
        {/* Top Navigation Bar */}
        <header className="flex h-16 shrink-0 items-center justify-between gap-3 border-b border-white/[0.08] bg-[#080808]/90 backdrop-blur-md px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              type="button"
              aria-label="Open navigation"
              onClick={() => setMobileNavOpen(true)}
              className="rounded-full border border-white/[0.14] bg-white/[0.06] p-2 text-[#fafafa] lg:hidden"
            >
              <Menu className="h-4 w-4" />
            </button>
            <div className="flex items-center gap-2 min-w-0">
              <span className="truncate text-sm font-medium text-[#fafafa]">
                {settings?.workspace_name || "AI Infrastructure Workspace"}
              </span>
              <span className="hidden sm:inline text-[#8b8a8a]">/</span>
              <span className="hidden sm:inline text-xs text-[#a7a6a6]">
                {NAV_ITEMS.find((n) => location.pathname.startsWith(n.to))
                  ?.label || "Overview"}
              </span>
            </div>
          </div>

          {/* Right Controls */}
          <div className="flex items-center gap-2.5">
            {/* Active Model Pill Selector */}
            <div className="hidden md:flex items-center">
              <label htmlFor="topbar-active-model" className="sr-only">
                Active model
              </label>
              <select
                id="topbar-active-model"
                value={`${activeProvider}::${activeModel}`}
                onChange={handleModelSwitch}
                className="h-9 rounded-full border border-white/[0.12] bg-[#0d0d0d] px-3.5 text-xs font-mono-tabular text-[#fafafa] focus:border-white/40 focus:outline-none"
              >
                {models.length === 0 ? (
                  <option value={`${activeProvider}::${activeModel}`}>
                    {activeProvider} / {activeModel}
                  </option>
                ) : (
                  models.map((m) => (
                    <option
                      key={`${m.provider_key}::${m.model_id}`}
                      value={`${m.provider_key}::${m.model_id}`}
                    >
                      {m.provider_name}: {m.display_name}
                      {m.has_credentials ? "" : " (Unconfigured)"}
                    </option>
                  ))
                )}
              </select>
            </div>

            {/* Live Connection Pill */}
            <div
              title={wsBadge.label}
              className="inline-flex h-9 items-center gap-2 rounded-full border border-white/[0.12] bg-white/[0.04] px-3 text-xs"
            >
              <span className={`h-2 w-2 rounded-full ${wsBadge.dot}`} />
              <span className="hidden sm:inline text-[#b6b5b5]">{wsBadge.short}</span>
            </div>

            {/* Notifications Popover */}
            <div className="relative">
              <button
                type="button"
                aria-label="Notifications"
                onClick={() => {
                  setNotifOpen((v) => !v);
                  setProfileOpen(false);
                }}
                className="relative flex h-9 w-9 items-center justify-center rounded-full border border-white/[0.12] bg-white/[0.04] text-[#b6b5b5] transition-colors hover:bg-white/[0.08] hover:text-[#fafafa]"
              >
                <Bell className="h-4 w-4" strokeWidth={1.6} />
                {unreadCount > 0 && (
                  <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-white px-1 text-[10px] font-semibold text-[#050505] tabular-nums">
                    {unreadCount > 9 ? "9+" : unreadCount}
                  </span>
                )}
              </button>

              {notifOpen && (
                <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-2xl border border-white/[0.12] bg-[#0a0a0a] p-3.5 shadow-2xl z-40">
                  <div className="flex items-center justify-between border-b border-white/[0.08] pb-2.5 mb-2.5">
                    <span className="text-xs font-medium text-[#fafafa]">
                      Live telemetry events
                    </span>
                    {liveEvents.length > 0 && (
                      <button
                        type="button"
                        onClick={() => void markAllEventsRead()}
                        className="text-xs text-[#b6b5b5] hover:text-[#fafafa]"
                      >
                        Mark all read
                      </button>
                    )}
                  </div>
                  <div className="max-h-72 overflow-y-auto space-y-1.5">
                    {liveEvents.length === 0 ? (
                      <div className="py-6 text-center text-xs text-[#8b8a8a]">
                        No monitoring events recorded yet
                      </div>
                    ) : (
                      liveEvents.slice(0, 12).map((ev) => (
                        <div
                          key={ev.id}
                          className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-[#fafafa] truncate">
                              {ev.title}
                            </span>
                            <span className="shrink-0 font-mono-tabular text-[11px] text-[#8b8a8a]">
                              {new Date(ev.timestamp).toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                                second: "2-digit",
                              })}
                            </span>
                          </div>
                          <p className="mt-1 text-[#a7a6a6] line-clamp-2">
                            {ev.message}
                          </p>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>

            {/* User Profile Pill */}
            <div className="relative">
              <button
                type="button"
                onClick={() => {
                  setProfileOpen((v) => !v);
                  setNotifOpen(false);
                }}
                className="flex h-9 items-center gap-2 rounded-full border border-white/[0.12] bg-white/[0.04] pl-2 pr-3 text-xs text-[#fafafa] hover:bg-white/[0.08]"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-[11px] font-semibold text-[#050505]">
                  {(user?.username || "U").slice(0, 1).toUpperCase()}
                </span>
                <span className="hidden sm:inline max-w-[100px] truncate">
                  {user?.username}
                </span>
                <ChevronDown className="h-3.5 w-3.5 text-[#a7a6a6]" />
              </button>

              {profileOpen && (
                <div className="absolute right-0 mt-2 w-56 rounded-2xl border border-white/[0.12] bg-[#0a0a0a] p-2 shadow-2xl z-40">
                  <div className="border-b border-white/[0.08] px-3 py-2.5">
                    <div className="truncate text-xs font-medium text-[#fafafa]">
                      {user?.full_name || user?.username}
                    </div>
                    <div className="truncate text-[11px] text-[#8b8a8a]">
                      {user?.email}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setProfileOpen(false);
                      navigate("/settings");
                    }}
                    className="mt-1 flex w-full items-center gap-2 rounded-xl px-3 py-2 text-xs text-[#b6b5b5] hover:bg-white/[0.06] hover:text-[#fafafa]"
                  >
                    <Settings className="h-3.5 w-3.5" />
                    <span>Workspace settings</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => void logout()}
                    className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-xs text-[#fca5a5] hover:bg-[#ef4444]/10"
                  >
                    <LogOut className="h-3.5 w-3.5" />
                    <span>Sign out</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {/* Page Body */}
        <main className="flex-1 overflow-y-auto bg-[#050505]">{children}</main>
      </div>
    </div>
  );
};

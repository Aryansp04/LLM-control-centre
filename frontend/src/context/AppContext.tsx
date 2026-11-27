import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  apiRequest,
  getStoredToken,
  LiveTelemetrySocket,
  onUnauthorized,
  setStoredToken,
  WsConnectionState,
} from "../api/client";
import {
  AuthResponse,
  LiveEvent,
  ModelInfo,
  MonitoringOverview,
  ProviderInfo,
  User,
  WorkspaceSettings,
} from "../types";

interface AppContextValue {
  user: User | null;
  authLoading: boolean;
  wsState: WsConnectionState;
  providers: ProviderInfo[];
  models: ModelInfo[];
  overview: MonitoringOverview | null;
  settings: WorkspaceSettings | null;
  liveEvents: LiveEvent[];
  activeProvider: string;
  activeModel: string;
  setActiveSelection: (providerKey: string, modelId: string) => void;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    username: string,
    password: string,
    fullName?: string
  ) => Promise<void>;
  logout: () => Promise<void>;
  refreshPlatformState: () => Promise<void>;
  markAllEventsRead: () => Promise<void>;
}

const AppContext = createContext<AppContextValue | undefined>(undefined);

export const AppProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [wsState, setWsState] = useState<WsConnectionState>("disconnected");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [overview, setOverview] = useState<MonitoringOverview | null>(null);
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [activeProvider, setActiveProvider] = useState<string>("gemini");
  const [activeModel, setActiveModel] = useState<string>("gemini-3.1-flash-lite-preview");

  const socketRef = useRef<LiveTelemetrySocket | null>(null);
  const initializedSelectionRef = useRef<boolean>(false);

  const refreshPlatformState = useCallback(async () => {
    if (!getStoredToken()) return;
    try {
      const [provData, modelData, overviewData, settingsData] = await Promise.all([
        apiRequest<ProviderInfo[]>("/api/providers"),
        apiRequest<ModelInfo[]>("/api/models"),
        apiRequest<MonitoringOverview>("/api/monitoring/overview"),
        apiRequest<WorkspaceSettings>("/api/settings"),
      ]);
      setProviders(provData);
      setModels(modelData);
      setOverview(overviewData);
      setSettings(settingsData);
      setLiveEvents(overviewData.recent_events || []);

      if (!initializedSelectionRef.current && settingsData) {
        const preferredProv = provData.find(
          (p) => p.provider_key === settingsData.default_provider
        );
        if (
          preferredProv &&
          preferredProv.has_api_key &&
          preferredProv.account_status !== "quota_exceeded" &&
          preferredProv.account_status !== "invalid_credentials"
        ) {
          setActiveProvider(settingsData.default_provider);
          setActiveModel(settingsData.default_model);
        } else {
          const workingModel = modelData.find(
            (m) =>
              m.has_credentials &&
              m.account_status !== "quota_exceeded" &&
              m.account_status !== "invalid_credentials"
          );
          if (workingModel) {
            setActiveProvider(workingModel.provider_key);
            setActiveModel(workingModel.model_id);
          }
        }
        initializedSelectionRef.current = true;
      }
    } catch {
      // Handled by individual pages / auth listener
    }
  }, []);

  const setActiveSelection = useCallback((providerKey: string, modelId: string) => {
    setActiveProvider(providerKey);
    setActiveModel(modelId);
  }, []);

  useEffect(() => {
    onUnauthorized(() => {
      setStoredToken(null);
      setUser(null);
      socketRef.current?.disconnect();
    });

    const boot = async () => {
      const tok = getStoredToken();
      if (!tok) {
        setAuthLoading(false);
        return;
      }
      try {
        const me = await apiRequest<User>("/api/auth/me");
        setUser(me);
      } catch {
        setStoredToken(null);
        setUser(null);
      } finally {
        setAuthLoading(false);
      }
    };
    void boot();
  }, []);

  useEffect(() => {
    if (!user) {
      socketRef.current?.disconnect();
      return;
    }

    void refreshPlatformState();

    const sock = new LiveTelemetrySocket(
      (ev) => {
        setLiveEvents((prev) => [ev, ...prev.filter((x) => x.id !== ev.id)].slice(0, 50));
        if (
          ev.type === "api_request_completed" ||
          ev.type === "provider_error" ||
          ev.type === "provider_status_changed" ||
          ev.type === "model_status_changed" ||
          ev.type === "health_check_completed" ||
          ev.type === "generation_started"
        ) {
          void refreshPlatformState();
        }
      },
      (st) => setWsState(st)
    );
    socketRef.current = sock;
    sock.connect();

    return () => {
      sock.disconnect();
    };
  }, [user, refreshPlatformState]);

  const login = async (email: string, password: string) => {
    const res = await apiRequest<AuthResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    setStoredToken(res.access_token);
    initializedSelectionRef.current = false;
    setUser(res.user);
  };

  const register = async (
    email: string,
    username: string,
    password: string,
    fullName?: string
  ) => {
    const res = await apiRequest<AuthResponse>("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        email,
        username,
        password,
        full_name: fullName || undefined,
      }),
    });
    setStoredToken(res.access_token);
    initializedSelectionRef.current = false;
    setUser(res.user);
  };

  const logout = async () => {
    try {
      await apiRequest("/api/auth/logout", { method: "POST" });
    } catch {
      // ignore logout error if token already expired
    } finally {
      socketRef.current?.disconnect();
      setStoredToken(null);
      setUser(null);
      setOverview(null);
      setLiveEvents([]);
    }
  };

  const markAllEventsRead = async () => {
    await apiRequest("/api/monitoring/events/read-all", { method: "POST" });
    setLiveEvents((prev) => prev.map((e) => ({ ...e, is_read: true })));
  };

  return (
    <AppContext.Provider
      value={{
        user,
        authLoading,
        wsState,
        providers,
        models,
        overview,
        settings,
        liveEvents,
        activeProvider,
        activeModel,
        setActiveSelection,
        login,
        register,
        logout,
        refreshPlatformState,
        markAllEventsRead,
      }}
    >
      {children}
    </AppContext.Provider>
  );
};

export function useApp(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) {
    throw new Error("useApp must be used inside AppProvider");
  }
  return ctx;
}

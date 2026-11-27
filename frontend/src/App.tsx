import React, { useState } from "react";
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { Loader2 } from "lucide-react";
import { AppProvider, useApp } from "./context/AppContext";
import { AppShell } from "./components/AppShell";
import { LandingPage } from "./pages/LandingPage";
import { AuthPage } from "./pages/AuthPage";
import { OverviewPage } from "./pages/OverviewPage";
import { ChatPage } from "./pages/ChatPage";
import { ModelsPage } from "./pages/ModelsPage";
import { ProvidersPage } from "./pages/ProvidersPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { ApiLogsPage } from "./pages/ApiLogsPage";
import { SettingsPage } from "./pages/SettingsPage";

const AppRoutes: React.FC = () => {
  const { user, authLoading } = useApp();
  const [showAuthPortal, setShowAuthPortal] = useState(false);
  const [pendingPath, setPendingPath] = useState<string>("/overview");
  const location = useLocation();
  const navigate = useNavigate();

  if (authLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-[#050505] text-[#a7a6a6] gap-2.5 text-sm">
        <Loader2 className="h-5 w-5 animate-spin text-[#fafafa]" />
        <span>Initializing...</span>
      </div>
    );
  }

  // Root `/` renders the pixel-faithful full-bleed CloudFront video Hero Stage
  if (location.pathname === "/") {
    if (!user && showAuthPortal) {
      return (
        <AuthPage
          onBackToStage={() => setShowAuthPortal(false)}
        />
      );
    }
    return (
      <LandingPage
        isAuthenticated={Boolean(user)}
        onEnterConsole={(target = "/overview") => {
          const dest = target === "/" ? "/overview" : target;
          if (user) {
            navigate(dest);
          } else {
            setPendingPath(dest);
            setShowAuthPortal(true);
          }
        }}
      />
    );
  }

  if (!user) {
    return (
      <AuthPage
        onBackToStage={() => navigate("/")}
      />
    );
  }

  return (
    <AppShell>
      <Routes>
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/providers" element={<ProvidersPage />} />
        <Route path="/monitoring" element={<MonitoringPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route path="/logs" element={<ApiLogsPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<Navigate to={pendingPath || "/overview"} replace />} />
      </Routes>
    </AppShell>
  );
};

export const App: React.FC = () => (
  <BrowserRouter
    future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
  >
    <AppProvider>
      <AppRoutes />
    </AppProvider>
  </BrowserRouter>
);

export default App;

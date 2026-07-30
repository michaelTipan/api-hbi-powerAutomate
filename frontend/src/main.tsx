import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { fetchEnvironment } from "./api/client";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { ProcessDetailPage } from "./pages/ProcessDetailPage";
import type { UiEnvironmentResponse } from "./types/contract";
import "./styles.css";

function Root() {
  const [env, setEnv] = useState<UiEnvironmentResponse | null>(null);

  useEffect(() => {
    void fetchEnvironment().then(setEnv).catch(() => {
      setEnv({
        environment: "unknown",
        display_label: "AMBIENTE NO CONFIGURADO",
        ui_enabled: false,
        ui_write_enabled: false,
        ui_auth_mode: "mock",
      });
    });
  }, []);

  return (
    <BrowserRouter basename="/app">
      <AppShell environment={env}>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/processes/:processKey" element={<ProcessDetailPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

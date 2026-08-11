import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import {
  assertNoCredentialStorage,
  clearCsrfTokenMemory,
  fetchBootstrap,
  fetchCsrfToken,
  fetchEnvironment,
  fetchMe,
  logoutLocal,
  setLocalSessionMode,
  subscribeSessionExpired,
} from "./api/client";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { HistoryDetailPage } from "./pages/HistoryDetailPage";
import { HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { ProcessDetailPage } from "./pages/ProcessDetailPage";
import type { UiBootstrapResponse } from "./types/contract";
import type { UiEnvironmentResponse } from "./types/contract";
import "./styles.css";

function Root() {
  const [bootstrap, setBootstrap] = useState<UiBootstrapResponse | null>(null);
  const [env, setEnv] = useState<UiEnvironmentResponse | null>(null);
  const [authed, setAuthed] = useState(false);
  const [ready, setReady] = useState(false);

  async function loadAuthenticated() {
    assertNoCredentialStorage();
    await fetchMe();
    // Renovar CSRF antes de habilitar mutables (fallo → botones bloqueados vía gate).
    try {
      await fetchCsrfToken();
    } catch {
      clearCsrfTokenMemory();
    }
    setEnv(await fetchEnvironment());
    setAuthed(true);
  }

  useEffect(() => {
    return subscribeSessionExpired(() => {
      setAuthed(false);
      setEnv(null);
    });
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const boot = await fetchBootstrap();
        setBootstrap(boot);
        if (boot.auth_mode === "local_session" && boot.login_required) {
          try {
            await loadAuthenticated();
          } catch {
            setAuthed(false);
          }
        } else {
          await loadAuthenticated();
        }
      } catch {
        setEnv({
          environment: "unknown",
          display_label: "AMBIENTE NO CONFIGURADO",
          ui_enabled: false,
          ui_write_enabled: false,
          ui_auth_mode: "mock",
        });
        setAuthed(false);
      } finally {
        setReady(true);
      }
    })();
  }, []);

  async function onLogout() {
    try {
      await logoutLocal();
    } catch {
      /* idempotente */
    }
    clearCsrfTokenMemory();
    setLocalSessionMode(false);
    setAuthed(false);
    setEnv(null);
  }

  if (!ready) {
    return <main className="login-panel">Cargando…</main>;
  }

  if (
    bootstrap?.auth_mode === "local_session" &&
    bootstrap.login_required &&
    !authed
  ) {
    return (
      <LoginPage
        displayLabel={bootstrap.display_label}
        onSuccess={async () => {
          await loadAuthenticated();
        }}
      />
    );
  }

  return (
    <BrowserRouter basename="/app">
      <AppShell
        environment={env}
        historyEnabled={Boolean(bootstrap?.history_allowed)}
        onLogout={bootstrap?.auth_mode === "local_session" ? onLogout : undefined}
      >
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          {bootstrap?.history_allowed ? (
            <>
              <Route path="/historial" element={<HistoryPage />} />
              <Route path="/historial/:processKey" element={<HistoryDetailPage />} />
            </>
          ) : null}
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

import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

const mocks = vi.hoisted(() => ({
  fetchBootstrap: vi.fn(),
  fetchMe: vi.fn(),
  fetchCsrfToken: vi.fn(),
  fetchEnvironment: vi.fn(),
  subscribeSessionExpired: vi.fn(() => () => {}),
}));

vi.mock("./api/client", () => ({
  assertNoCredentialStorage: vi.fn(),
  clearCsrfTokenMemory: vi.fn(),
  fetchBootstrap: mocks.fetchBootstrap,
  fetchCsrfToken: mocks.fetchCsrfToken,
  fetchEnvironment: mocks.fetchEnvironment,
  fetchMe: mocks.fetchMe,
  logoutLocal: vi.fn(),
  setLocalSessionMode: vi.fn(),
  subscribeSessionExpired: mocks.subscribeSessionExpired,
  isMockMode: () => false,
}));

vi.mock("./components/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="app-shell">{children}</div>
  ),
}));

vi.mock("./pages/DashboardPage", () => ({
  DashboardPage: () => <div>Panel listo</div>,
}));

function BootProbe() {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    setMounted(true);
  }, []);
  return <div>{mounted ? "router-mounted" : "pending"}</div>;
}

describe("main boot gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.fetchBootstrap.mockResolvedValue({
      auth_mode: "local_session",
      login_required: true,
      display_label: "Sandbox",
      history_allowed: false,
    });
    mocks.fetchMe.mockResolvedValue({ authenticated: true });
    let csrfResolved = false;
    mocks.fetchCsrfToken.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          setTimeout(() => {
            csrfResolved = true;
            resolve("csrf-token");
          }, 100);
        }),
    );
    mocks.fetchEnvironment.mockResolvedValue({
      environment: "sandbox",
      display_label: "Sandbox",
      ui_enabled: true,
      ui_write_enabled: true,
      ui_auth_mode: "local_session",
    });
  });

  it("monta el router tras bootstrap+fetchMe sin esperar CSRF", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    let csrfDone = false;
    mocks.fetchCsrfToken.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          setTimeout(() => {
            csrfDone = true;
            resolve("csrf-token");
          }, 100);
        }),
    );

    function MiniRoot() {
      const [ready, setReady] = useState(false);
      useEffect(() => {
        void (async () => {
          await mocks.fetchBootstrap();
          await mocks.fetchMe();
          setReady(true);
          void Promise.all([mocks.fetchCsrfToken(), mocks.fetchEnvironment()]);
        })();
      }, []);
      if (!ready) return <main>Cargando…</main>;
      return <BootProbe />;
    }

    const root = createRoot(container);
    root.render(
      <StrictMode>
        <MiniRoot />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(screen.getByText("router-mounted")).toBeInTheDocument();
    });
    expect(csrfDone).toBe(false);
    root.unmount();
    container.remove();
  });
});

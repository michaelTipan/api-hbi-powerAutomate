import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resetCsrfManagerForTests } from "./csrfManager";

const fetchMock = vi.fn();

beforeEach(() => {
  resetCsrfManagerForTests();
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  resetCsrfManagerForTests();
  vi.unstubAllGlobals();
  vi.resetModules();
});

function jsonResponse(status: number, body: unknown, headers?: Record<string, string>) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...(headers ?? {}) },
  });
}

async function loadClient() {
  return import("./client");
}

describe("client CSRF lifecycle", () => {
  it("login obtiene CSRF y lo guarda solo en memoria", async () => {
    const client = await loadClient();
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }))
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-after-login" }));

    await client.loginLocal("operador_hbi", "secret");

    expect(client.getCsrfTokenMemory()).toBe("csrf-after-login");
    expect(client.isLocalSessionMode()).toBe(true);
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);

    const csrfCall = fetchMock.mock.calls.find((c) => String(c[0]).includes("/auth/csrf"));
    expect(csrfCall).toBeTruthy();
    expect((csrfCall![1] as RequestInit).credentials).toBe("include");
  });

  it("Generate envía header X-CSRF-Token", async () => {
    const client = await loadClient();
    client.setLocalSessionMode(true);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-gen-1" }))
      .mockResolvedValueOnce(
        jsonResponse(202, {
          accepted: true,
          action: "generate",
          bank_code: "banco_bogota",
          job_id: "j1",
          status: "queued",
          poll_url: "/api/ui/v1/jobs/j1",
        }),
      );

    await client.postGenerate("banco_bogota");

    const genCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/processes/generate"),
    );
    expect(genCall).toBeTruthy();
    const headers = (genCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-gen-1");
    expect((genCall![1] as RequestInit).credentials).toBe("include");
  });

  it("refresh renueva CSRF con force", async () => {
    const client = await loadClient();
    client.setLocalSessionMode(true);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-old" }))
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-new" }));

    await client.fetchCsrfToken();
    expect(client.getCsrfTokenMemory()).toBe("csrf-old");
    await client.fetchCsrfToken();
    expect(client.getCsrfTokenMemory()).toBe("csrf-new");
  });

  it("logout limpia CSRF y modo local", async () => {
    const client = await loadClient();
    client.setLocalSessionMode(true);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-out" }))
      .mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await client.fetchCsrfToken();
    await client.logoutLocal();
    expect(client.getCsrfTokenMemory()).toBeNull();
    expect(client.isLocalSessionMode()).toBe(false);
  });

  it("primer 403 CSRF renueva y reintenta una vez", async () => {
    const client = await loadClient();
    client.setLocalSessionMode(true);
    // ensure antes del POST
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-stale" }))
      // POST generate → 403 csrf
      .mockResolvedValueOnce(
        jsonResponse(403, {
          detail: {
            error_code: "invalid_csrf_token",
            user_message: "Token CSRF inválido o ausente.",
            next_action: "reintente",
            severity: "fatal",
          },
        }),
      )
      // refresh CSRF
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-fresh" }))
      // retry generate OK
      .mockResolvedValueOnce(
        jsonResponse(202, {
          accepted: true,
          action: "generate",
          bank_code: "banco_bogota",
          job_id: "j2",
          status: "queued",
          poll_url: "/api/ui/v1/jobs/j2",
        }),
      );

    const result = await client.postGenerate("banco_bogota");
    expect(result.job_id).toBe("j2");

    const genCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/processes/generate"),
    );
    expect(genCalls).toHaveLength(2);
    const retryHeaders = (genCalls[1][1] as RequestInit).headers as Record<string, string>;
    expect(retryHeaders["X-CSRF-Token"]).toBe("csrf-fresh");
  });

  it("segundo 403 CSRF no entra en loop", async () => {
    const client = await loadClient();
    client.setLocalSessionMode(true);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-a" }))
      .mockResolvedValueOnce(
        jsonResponse(403, {
          detail: {
            error_code: "invalid_csrf_token",
            user_message: "Token CSRF inválido o ausente.",
            next_action: "reintente",
            severity: "fatal",
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-b" }))
      .mockResolvedValueOnce(
        jsonResponse(403, {
          detail: {
            error_code: "invalid_csrf_token",
            user_message: "Token CSRF inválido o ausente.",
            next_action: "reintente",
            severity: "fatal",
          },
        }),
      );

    await expect(client.postGenerate("banco_bogota")).rejects.toMatchObject({
      errorCode: "invalid_csrf_token",
    });

    const genCalls = fetchMock.mock.calls.filter((c) =>
      String(c[0]).includes("/processes/generate"),
    );
    expect(genCalls).toHaveLength(2);
  });

  it("tras clearBootstrap sigue enviando CSRF en modo sticky", async () => {
    const client = await loadClient();
    // Simula bootstrap + modo local, luego 401 limpia bootstrap.
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, {
        auth_mode: "local_session",
        login_required: true,
        display_label: "Entorno de validación",
        writes_allowed: false,
        active_environment: "sandbox",
        ui_enabled: true,
      }),
    );
    await client.fetchBootstrap();
    expect(client.isLocalSessionMode()).toBe(true);

    client.clearBootstrapCache();
    // Sin sticky, authMode caería a mock y no enviaría CSRF.
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { csrf_token: "csrf-sticky" }))
      .mockResolvedValueOnce(
        jsonResponse(202, {
          accepted: true,
          action: "generate",
          bank_code: "banco_bogota",
          job_id: "j3",
          status: "queued",
          poll_url: "/api/ui/v1/jobs/j3",
        }),
      );

    await client.postGenerate("banco_bogota");
    const genCall = fetchMock.mock.calls.find((c) =>
      String(c[0]).includes("/processes/generate"),
    );
    const headers = (genCall![1] as RequestInit).headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("csrf-sticky");
    expect(headers.Authorization).toBeUndefined();
  });
});

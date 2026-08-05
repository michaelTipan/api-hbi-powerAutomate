import type { Page, Route } from "@playwright/test";
import {
  E2E_CSRF,
  E2E_PASSWORD,
  E2E_USERNAME,
  amortRecoveryProcessKey,
  banksCapabilities,
  bootstrapEnabled,
  completedJob,
  environmentSandbox,
  getProcessDetail,
  historyItems,
  meOperator,
  mergeProcessKey,
  mockProcessList,
  notifyProcessKey,
  reviewProcessKey,
} from "../mocks/fixtures";

export type MockAuthState = {
  authenticated: boolean;
  csrfIssued: boolean;
  csrfCalls: number;
  /** Retraso artificial en GET csrf (simula sesión preparándose). */
  csrfDelayMs?: number;
  /** Si false, bootstrap exige login. */
  loginRequired?: boolean;
  /** Si false, writes_allowed=false en bootstrap. */
  writesAllowed?: boolean;
};

export type MockApiOptions = Partial<MockAuthState> & {
  /** Sobrescribe detalle de un proceso por clave. */
  processOverrides?: Record<string, ReturnType<typeof getProcessDetail>>;
  /** Jobs simulados por id. */
  jobs?: Record<string, ReturnType<typeof completedJob>>;
};

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

function pathOnly(url: string): string {
  try {
    const u = new URL(url);
    return u.pathname;
  } catch {
    return url;
  }
}

/**
 * Enruta todas las llamadas /api/ui/v1/* con datos deterministas.
 * Usar una instancia por test para evitar fugas de estado entre specs.
 */
export async function installUiApiMocks(
  page: Page,
  opts: MockApiOptions = {},
): Promise<MockAuthState> {
  const state: MockAuthState = {
    authenticated: opts.authenticated ?? false,
    csrfIssued: opts.csrfIssued ?? false,
    csrfCalls: 0,
    csrfDelayMs: opts.csrfDelayMs ?? 0,
    loginRequired: opts.loginRequired ?? true,
    writesAllowed: opts.writesAllowed ?? true,
  };

  const jobs: Record<string, ReturnType<typeof completedJob>> = {
    ...(opts.jobs ?? {}),
  };

  await page.route("**/api/ui/v1/**", async (route) => {
    const path = pathOnly(route.request().url());
    const method = route.request().method().toUpperCase();

    if (path.endsWith("/bootstrap") && method === "GET") {
      return json(route, {
        ...bootstrapEnabled,
        login_required: state.loginRequired ?? true,
        writes_allowed: state.writesAllowed ?? true,
      });
    }

    if (path.endsWith("/auth/csrf") && method === "GET") {
      state.csrfCalls += 1;
      if (
        state.csrfDelayMs &&
        state.csrfDelayMs > 0 &&
        state.authenticated &&
        state.csrfCalls >= 1
      ) {
        await new Promise((r) => setTimeout(r, state.csrfDelayMs));
      }
      state.csrfIssued = true;
      return json(route, { csrf_token: E2E_CSRF });
    }

    if (path.endsWith("/auth/login") && method === "POST") {
      const body = route.request().postDataJSON() as {
        username?: string;
        password?: string;
      };
      if (body.username === E2E_USERNAME && body.password === E2E_PASSWORD) {
        state.authenticated = true;
        return json(route, { ok: true });
      }
      return json(route, { detail: { user_message: "Credenciales inválidas." } }, 401);
    }

    if (path.endsWith("/auth/logout") && method === "POST") {
      state.authenticated = false;
      state.csrfIssued = false;
      return json(route, { ok: true });
    }

    if (path.endsWith("/auth/me") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      return json(route, meOperator);
    }

    if (path.endsWith("/environment") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      return json(route, environmentSandbox);
    }

    if (path.endsWith("/banks") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      return json(route, banksCapabilities);
    }

    if (path.endsWith("/processes") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      return json(route, mockProcessList());
    }

    if (path.includes("/process-history/") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      const key = decodeURIComponent(path.split("/process-history/")[1] ?? "");
      const detail = opts.processOverrides?.[key] ?? getProcessDetail(key);
      if (!detail) return json(route, { detail: "No encontrado" }, 404);
      return json(route, detail);
    }

    if (path.endsWith("/process-history") && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      return json(route, {
        environment: "sandbox",
        items: historyItems,
        unavailable_banks: [],
      });
    }

    const processMatch = path.match(/\/processes\/([^/]+)$/);
    if (processMatch && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      const key = decodeURIComponent(processMatch[1]);
      const detail = opts.processOverrides?.[key] ?? getProcessDetail(key);
      if (!detail) return json(route, { detail: "No encontrado" }, 404);
      return json(route, detail);
    }

    const jobMatch = path.match(/\/jobs\/([^/]+)$/);
    if (jobMatch && method === "GET") {
      if (!state.authenticated) {
        return json(route, { detail: "No autenticado" }, 401);
      }
      const jobId = decodeURIComponent(jobMatch[1]);
      const job =
        jobs[jobId] ??
        completedJob(jobId, reviewProcessKey, "generate");
      return json(route, job);
    }

    if (path.endsWith("/processes/generate") && method === "POST") {
      const jobId = "job-generate-e2e";
      jobs[jobId] = completedJob(jobId, reviewProcessKey, "generate");
      return json(
        route,
        {
          accepted: true,
          action: "generate",
          bank_code: "banco_bogota",
          job_id: jobId,
          status: "queued",
          poll_url: `/api/ui/v1/jobs/${jobId}`,
        },
        202,
      );
    }

    if (path.endsWith("/processes/finalize") && method === "POST") {
      const jobId = "job-finalize-e2e";
      jobs[jobId] = completedJob(jobId, reviewProcessKey, "finalize");
      return json(
        route,
        {
          accepted: true,
          action: "finalize",
          bank_code: "banco_bancolombia",
          process_key: reviewProcessKey,
          job_id: jobId,
          status: "queued",
          poll_url: `/api/ui/v1/jobs/${jobId}`,
        },
        202,
      );
    }

    if (path.endsWith("/processes/notify") && method === "POST") {
      const jobId = "job-notify-e2e";
      jobs[jobId] = completedJob(jobId, notifyProcessKey, "notify");
      return json(
        route,
        {
          accepted: true,
          action: "notify",
          bank_code: "banco_bogota",
          process_key: notifyProcessKey,
          job_id: jobId,
          status: "queued",
          poll_url: `/api/ui/v1/jobs/${jobId}`,
        },
        202,
      );
    }

    if (path.endsWith("/processes/merge") && method === "POST") {
      const jobId = "job-merge-e2e";
      jobs[jobId] = completedJob(jobId, mergeProcessKey, "merge");
      return json(
        route,
        {
          accepted: true,
          action: "merge",
          bank_code: "banco_bancolombia",
          process_key: mergeProcessKey,
          job_id: jobId,
          status: "queued",
          poll_url: `/api/ui/v1/jobs/${jobId}`,
        },
        202,
      );
    }

    if (path.endsWith("/processes/amortization") && method === "POST") {
      const jobId = "job-amort-e2e";
      jobs[jobId] = completedJob(jobId, amortRecoveryProcessKey, "amortization");
      return json(
        route,
        {
          accepted: true,
          action: "amortization",
          bank_code: "banco_bogota",
          process_key: amortRecoveryProcessKey,
          job_id: jobId,
          status: "queued",
          poll_url: `/api/ui/v1/jobs/${jobId}`,
        },
        202,
      );
    }

    // Fallback explícito para depurar mocks faltantes.
    return json(
      route,
      { detail: `E2E mock no implementado: ${method} ${path}` },
      501,
    );
  });

  return state;
}

export async function loginViaUi(page: Page): Promise<void> {
  await page.goto("./");
  await page.locator("#login-username").fill(E2E_USERNAME);
  await page.locator("#login-password").fill(E2E_PASSWORD);
  await page.getByRole("button", { name: "Entrar" }).click();
  await page.getByRole("heading", { name: "Panel" }).waitFor();
}

export async function installAndLogin(
  page: Page,
  opts: MockApiOptions = {},
): Promise<MockAuthState> {
  const state = await installUiApiMocks(page, opts);
  await loginViaUi(page);
  state.authenticated = true;
  return state;
}

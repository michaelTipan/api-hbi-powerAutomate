import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mocks = vi.hoisted(() => ({
  fetchBanks: vi.fn(),
  fetchProcesses: vi.fn(),
  fetchJob: vi.fn(),
  postGenerate: vi.fn(),
  useCsrfReady: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchBanks: mocks.fetchBanks,
  fetchProcesses: mocks.fetchProcesses,
  fetchJob: mocks.fetchJob,
  postGenerate: mocks.postGenerate,
}));

vi.mock("../api/useCsrfReady", () => ({
  useCsrfReady: mocks.useCsrfReady,
}));

import { DashboardPage } from "./DashboardPage";

describe("DashboardPage — gate CSRF", () => {
  beforeEach(() => {
    mocks.fetchBanks.mockResolvedValue([
      {
        bank_code: "banco_bogota",
        bank_name: "Banco Bogotá",
        available_actions: { generate: { allowed: true, reason: null } },
      },
    ]);
    mocks.fetchProcesses.mockResolvedValue({ environment: "sandbox", items: [] });
  });

  it("bloquea botones mutables mientras prepara sesión segura", async () => {
    mocks.useCsrfReady.mockReturnValue({ csrfReady: false, csrfPreparing: true });
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    expect(
      await screen.findByText(/Preparando sesión segura/),
    ).toBeInTheDocument();
    const btn = await screen.findByRole("button", { name: "Iniciar validación" });
    expect(btn).toBeDisabled();
  });

  it("habilita botones cuando el CSRF está listo", async () => {
    mocks.useCsrfReady.mockReturnValue({ csrfReady: true, csrfPreparing: false });
    render(
      <MemoryRouter>
        <DashboardPage />
      </MemoryRouter>,
    );
    const btn = await screen.findByRole("button", { name: "Iniciar validación" });
    expect(btn).not.toBeDisabled();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mocks = vi.hoisted(() => ({
  fetchProcesses: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcesses: mocks.fetchProcesses,
}));

import { HistoryPage } from "./HistoryPage";

describe("HistoryPage — Fase 1 (Control)", () => {
  it("lista procesos del Control sin botón de nuevo proceso", async () => {
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [
        {
          process_key: "payment-validation|banco_bogota|2026-08-02|abc",
          bank_code: "banco_bogota",
          process_date: "2026-08-02",
          environment: "sandbox",
          operational_status: "EN_REVISION",
          operational_title: "Revisión pendiente",
          operational_message: "Complete el Excel de revisión.",
          control_estado_proceso: "REVISION_CREADA",
          is_active: true,
          error_count: 0,
          next_actions: [],
        },
      ],
      unavailable_banks: [],
    });

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "Historial" })).toBeInTheDocument();
    expect(screen.getByText("Banco Bogotá")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continuar proceso" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Iniciar validación/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Nuevo proceso/i)).not.toBeInTheDocument();
  });

  it("muestra vacío cuando Control no tiene procesos", async () => {
    mocks.fetchProcesses.mockResolvedValue({
      environment: "sandbox",
      items: [],
      unavailable_banks: [],
    });

    render(
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>,
    );

    expect(
      await screen.findByText(/No hay procesos registrados en el Control activo/),
    ).toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const mocks = vi.hoisted(() => ({
  fetchProcessHistory: vi.fn(),
}));

vi.mock("../api/client", () => ({
  fetchProcessHistory: mocks.fetchProcessHistory,
}));

import { HistoryPage } from "./HistoryPage";

describe("HistoryPage — Fase 2", () => {
  it("lista activos y archivados sin botón de nuevo proceso", async () => {
    mocks.fetchProcessHistory.mockResolvedValue({
      environment: "sandbox",
      items: [
        {
          process_key: "payment-validation|banco_bogota|2026-08-02|abc",
          bank_code: "banco_bogota",
          bank_name: "Banco Bogotá",
          process_date: "2026-08-02",
          environment: "sandbox",
          operational_status: "EN_REVISION",
          operational_title: "Revisión pendiente",
          operational_message: "Complete el Excel de revisión.",
          control_estado_proceso: "REVISION_CREADA",
          source: "active",
          read_only: false,
        },
        {
          process_key: "payment-validation|banco_bancolombia|2026-07-01|old",
          bank_code: "banco_bancolombia",
          bank_name: "Bancolombia",
          process_date: "2026-07-01",
          environment: "sandbox",
          operational_status: "COMPLETADO",
          operational_title: "Proceso completado",
          operational_message: "Cerrado.",
          control_estado_proceso: "AMORTIZACION_APLICADA",
          source: "archive",
          read_only: true,
          closed_at: "2026-07-01T18:00:00Z",
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
    expect(screen.getAllByText("Banco Bogotá").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Bancolombia").length).toBeGreaterThan(0);
    expect(screen.getByText("Archivo")).toBeInTheDocument();
    expect(screen.getByText("Activo")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Continuar proceso" })).toBeInTheDocument();
    const detail = screen.getByRole("link", { name: "Ver detalle" });
    expect(detail.getAttribute("href") || "").toContain("/historial/");
    expect(screen.queryByRole("button", { name: /Iniciar validación/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/Nuevo proceso/i)).not.toBeInTheDocument();
  });

  it("muestra vacío cuando no hay filas", async () => {
    mocks.fetchProcessHistory.mockResolvedValue({
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
      await screen.findByText(/No hay procesos para mostrar/),
    ).toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobStatusModal } from "./JobStatusModal";

describe("JobStatusModal — fallo de revisión", () => {
  it("lista problemas concretos y el enlace al Excel de revisión", async () => {
    const onDismiss = vi.fn();
    render(
      <JobStatusModal
        view={{
          kind: "error",
          title: "No se pudo completar",
          message:
            "Se encontraron 2 problemas en la revisión. Corrija todos los puntos listados, guarde y vuelva a verificar.",
          issues: [
            {
              id: "i1",
              message:
                "Marcó Validar Pago = SI pero el total aplicado es cero o negativo (NORMAL o ATRASADO).",
              location: "Hoja: Distribucion_Pagos · Fila: 6 · Crédito: CREDITO # 265",
            },
            {
              id: "i2",
              message: "Los valores distribuidos no coinciden con el monto registrado por el banco.",
              location: "Hoja: Distribucion_Pagos · Fila: 4 · ID pago: ID1",
            },
          ],
          links: [
            {
              rel: "review_excel",
              label: "Abrir archivo de revisión",
              path: null,
              web_url: "https://sharepoint.example/review.xlsx",
              open_mode: "sharepoint",
            },
          ],
        }}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByRole("heading", { name: "No se pudo completar" })).toBeInTheDocument();
    expect(screen.getByText(/Se encontraron 2 problemas/)).toBeInTheDocument();
    expect(
      screen.getByText(/total aplicado es cero o negativo/i),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Hoja:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Fila:/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Abrir archivo de revisión/i }),
    ).toHaveAttribute("href", "https://sharepoint.example/review.xlsx");

    await userEvent.setup().click(screen.getByRole("button", { name: "Entendido" }));
    expect(onDismiss).toHaveBeenCalled();
  });
});

describe("JobStatusModal — warning con CTA secundario", () => {
  it("muestra el botón secundario y ejecuta onClick", async () => {
    const onDismiss = vi.fn();
    const onSecondary = vi.fn();
    render(
      <JobStatusModal
        view={{
          kind: "warning",
          title: "Revisión requerida",
          message: "Se encontró 1 problema de amortización.",
          secondaryCta: {
            label: "Ver problemas de amortización",
            onClick: onSecondary,
          },
        }}
        onDismiss={onDismiss}
      />,
    );

    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: /Ver problemas de amortización/i }));
    expect(onSecondary).toHaveBeenCalled();
    expect(onDismiss).not.toHaveBeenCalled();
  });
});

describe("JobStatusModal — éxito con catálogo N", () => {
  it("muestra un solo CTA que abre el catálogo (sin volcar links inline)", async () => {
    const onDismiss = vi.fn();
    const onOpen = vi.fn();
    render(
      <JobStatusModal
        view={{
          kind: "success",
          title: "PDF consolidado listo",
          message: "Se generó el PDF consolidado.",
          catalogCta: {
            label: "PDFs consolidados (2)",
            onOpen,
          },
        }}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByRole("button", { name: "PDFs consolidados (2)" })).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "PDFs consolidados (2)" }));
    expect(onOpen).toHaveBeenCalled();
  });
});

describe("JobStatusModal — éxito con artefactos", () => {
  it("muestra enlaces al histórico y al soporte de asientos", async () => {
    const onDismiss = vi.fn();
    render(
      <JobStatusModal
        view={{
          kind: "success",
          title: "Revisión finalizada",
          message:
            "Se finalizó la revisión correctamente. Se guardó el histórico del día y el archivo para cargar los asientos contables.",
          links: [
            {
              rel: "historical",
              label: "Abrir histórico",
              path: "hist.xlsx",
              web_url: "https://sharepoint.example/hist.xlsx",
              open_mode: "sharepoint",
            },
            {
              rel: "secretary_file",
              label: "Abrir asientos pendientes",
              path: "sec.xlsx",
              web_url: "https://sharepoint.example/sec.xlsx",
              open_mode: "sharepoint",
            },
          ],
        }}
        onDismiss={onDismiss}
      />,
    );

    expect(screen.getByRole("heading", { name: "Revisión finalizada" })).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Abrir histórico/i }),
    ).toHaveAttribute("href", "https://sharepoint.example/hist.xlsx");
    expect(
      screen.getByRole("link", { name: /Abrir asientos pendientes/i }),
    ).toHaveAttribute("href", "https://sharepoint.example/sec.xlsx");

    await userEvent.setup().click(screen.getByRole("button", { name: "Continuar" }));
    expect(onDismiss).toHaveBeenCalled();
  });
});

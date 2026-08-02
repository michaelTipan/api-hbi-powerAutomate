import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { OperationalIssuePanel } from "./OperationalIssuePanel";
import type { UiOperationalIssue } from "../types/contract";

function issue(overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue {
  return {
    issue_id: "HBI-FINALIZE-invalid_estado_pago-12345678",
    stage: "finalize",
    category: "correction_required",
    severity: "warning",
    recoverable: true,
    title: "La revisión requiere correcciones.",
    user_message: "No se pudo finalizar el archivo de revisión.",
    location: {
      file_name: "validacion_pagos_demo.xlsx",
      sheet: "Distribucion_Pagos",
      row: 14,
      column: "Estado Pago",
      credit: "37",
      payment_id: null,
      client_name: null,
    },
    value_found: "PENDIENTE",
    expected_values: ["ADELANTADO", "ATRASADO", "NORMAL", "REVISION_MANUAL"],
    next_action: "Corrija el valor, guarde el archivo y vuelva a verificar.",
    retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
    links: [
      {
        rel: "review_excel",
        label: "Abrir Excel de revisión",
        path: "02 VALIDACION PAGOS/01 REVISION/validacion_pagos_demo.xlsx",
        web_url: "https://gecolsacat.sharepoint.com/sites/OperacionesHBICapital",
        open_mode: "sharepoint",
      },
    ],
    technical_reference: "job:abc123|code:invalid_estado_pago",
    ...overrides,
  };
}

describe("OperationalIssuePanel", () => {
  it("muestra título, mensaje, ubicación y siguiente acción", () => {
    render(<OperationalIssuePanel issue={issue()} />);
    expect(screen.getByText("La revisión requiere correcciones.")).toBeInTheDocument();
    expect(
      screen.getByText("No se pudo finalizar el archivo de revisión."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Hoja: Distribucion_Pagos/)).toBeInTheDocument();
    expect(screen.getByText(/Fila: 14/)).toBeInTheDocument();
    expect(
      screen.getByText("Corrija el valor, guarde el archivo y vuelva a verificar."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Abrir Excel de revisión" }),
    ).toHaveAttribute(
      "href",
      "https://gecolsacat.sharepoint.com/sites/OperacionesHBICapital",
    );
  });

  it("muestra cliente, crédito e ID pago en la ubicación", () => {
    render(
      <OperationalIssuePanel
        issue={issue({
          location: {
            file_name: "rev.xlsx",
            sheet: "Errores",
            row: 2,
            column: null,
            credit: "215",
            payment_id: "PAY-9",
            client_name: "CLIENTE DEMO",
          },
          links: [
            {
              rel: "error_extract",
              label: "extracto_malo.pdf",
              path: null,
              web_url: "https://example.com/a.pdf",
              open_mode: "sharepoint",
            },
            {
              rel: "error_folder",
              label: "CREDITO 215",
              path: null,
              web_url: "https://example.com/folder",
              open_mode: "sharepoint",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText(/Cliente: CLIENTE DEMO/)).toBeInTheDocument();
    expect(screen.getByText(/Crédito: 215/)).toBeInTheDocument();
    expect(screen.getByText(/ID pago: PAY-9/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "extracto_malo.pdf" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "CREDITO 215" })).toBeInTheDocument();
  });

  it("invoca onRetry al pulsar el botón de reintento cuando retry.allowed=true", async () => {
    const onRetry = vi.fn();
    const user = userEvent.setup();
    render(<OperationalIssuePanel issue={issue()} onRetry={onRetry} />);
    await user.click(screen.getByRole("button", { name: "Verificar nuevamente" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("no muestra botón de reintento cuando retry.allowed=false", () => {
    render(
      <OperationalIssuePanel
        issue={issue({ retry: { allowed: false, action: null, label: null } })}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("no tiene violaciones de accesibilidad detectables por axe", async () => {
    const { container } = render(<OperationalIssuePanel issue={issue()} onRetry={vi.fn()} />);
    // color-contrast requiere render real (canvas); jsdom no lo soporta.
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CorrectionTargetsDrawer } from "./CorrectionTargetsDrawer";
import type { UiOperationalIssue } from "../types/contract";

function issue(overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue {
  return {
    issue_id: "review-errores-0-2",
    stage: "generate",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Extracto · Crédito 215",
    user_message: "PDF ilegible.",
    location: {
      file_name: "rev.xlsx",
      sheet: "Errores",
      row: 2,
      column: null,
      credit: "215",
      payment_id: null,
      client_name: "CLIENTE DEMO",
    },
    value_found: null,
    expected_values: [],
    next_action: "Corrija el PDF y regenere.",
    retry: null,
    links: [
      {
        rel: "error_extract",
        label: "Abrir extracto",
        path: null,
        web_url: "https://example.com/extracto.pdf",
        open_mode: "sharepoint",
      },
      {
        rel: "error_folder",
        label: "Abrir carpeta del crédito",
        path: null,
        web_url: "https://example.com/folder",
        open_mode: "sharepoint",
      },
    ],
    technical_reference: "fecha_limite_extracto_not_readable",
    ...overrides,
  };
}

describe("CorrectionTargetsDrawer", () => {
  it("lista destinos con copy de negocio y botones Abrir", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <CorrectionTargetsDrawer open issues={[issue()]} onClose={onClose} />,
    );
    expect(screen.getByRole("heading", { name: /Destinos de corrección/i })).toBeInTheDocument();
    expect(screen.getByText(/Extracto · Crédito 215/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir extracto" })).toHaveAttribute(
      "href",
      "https://example.com/extracto.pdf",
    );
    expect(screen.getByRole("link", { name: "Abrir carpeta del crédito" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("no renderiza cuando open=false", () => {
    const { container } = render(
      <CorrectionTargetsDrawer open={false} issues={[issue()]} onClose={() => undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

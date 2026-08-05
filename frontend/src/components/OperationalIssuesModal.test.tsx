import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { OperationalIssuesModal } from "./OperationalIssuesModal";
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
      {
        rel: "error_bank_excel",
        label: "Abrir Excel del banco",
        path: null,
        web_url: "https://example.com/banco.xlsx",
        open_mode: "sharepoint",
      },
    ],
    technical_reference: "fecha_limite_extracto_not_readable",
    ...overrides,
  };
}

describe("OperationalIssuesModal", () => {
  it("lista paneles con detalle y todos los enlaces", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <OperationalIssuesModal open issues={[issue()]} onClose={onClose} />,
    );
    expect(
      screen.getByRole("heading", { name: /Problemas operativos \(1\)/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("PDF ilegible.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir extracto" })).toHaveAttribute(
      "href",
      "https://example.com/extracto.pdf",
    );
    expect(screen.getByRole("link", { name: "Abrir carpeta del crédito" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir Excel del banco" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("no renderiza cuando open=false", () => {
    const { container } = render(
      <OperationalIssuesModal open={false} issues={[issue()]} onClose={() => undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("filtra por búsqueda con muchos casos", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 8 }, (_, i) =>
      issue({
        issue_id: `review-errores-${i}`,
        title: i === 3 ? "Caso único buscable" : `Caso ${i}`,
        user_message: i === 3 ? "Mensaje especial XYZ" : `Msg ${i}`,
        links: [],
        technical_reference: "mismo_codigo",
      }),
    );
    render(<OperationalIssuesModal open issues={many} onClose={() => undefined} />);
    await user.type(
      screen.getByPlaceholderText(/Buscar por crédito/i),
      "especial XYZ",
    );
    expect(screen.getByText("Mensaje especial XYZ")).toBeInTheDocument();
    expect(screen.queryByText("Msg 0")).not.toBeInTheDocument();
  });

  it("con pocos casos lista directo sin chips de grupo", () => {
    render(
      <OperationalIssuesModal
        open
        issues={[
          issue({
            issue_id: "a",
            technical_reference: "PDF_TEXT_NOT_EXTRACTABLE",
            links: [],
          }),
          issue({
            issue_id: "b",
            title: "Otro",
            technical_reference: "ACCOUNTING_PARSE_FAILED",
            links: [],
          }),
        ]}
        onClose={() => undefined}
      />,
    );
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getAllByText("PDF ilegible.")).toHaveLength(2);
    expect(screen.queryByText("Detalle técnico")).not.toBeInTheDocument();
    expect(screen.queryByText(/Archivo:/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: /PDF sin texto legible/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: /Formato de asiento no reconocido/i }),
    ).toBeInTheDocument();
  });

  it("con muchos casos y varios códigos muestra chips de filtro en español", async () => {
    const user = userEvent.setup();
    const many = Array.from({ length: 6 }, (_, i) =>
      issue({
        issue_id: `review-errores-${i}`,
        title: `Caso ${i}`,
        user_message: `Msg ${i}`,
        links: [],
        technical_reference:
          i < 3 ? "PDF_TEXT_NOT_EXTRACTABLE" : "ACCOUNTING_PARSE_FAILED",
      }),
    );
    render(<OperationalIssuesModal open issues={many} onClose={() => undefined} />);
    expect(screen.getByRole("tablist", { name: /Filtrar por tipo/i })).toBeInTheDocument();
    expect(screen.queryByText(/Missing /i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: /PDF sin texto legible \(3\)/i }));
    expect(screen.getByText("Msg 0")).toBeInTheDocument();
    expect(screen.queryByText("Msg 5")).not.toBeInTheDocument();
  });

  it("agrupa errores de Finalize por fila y muestra CTAs una sola vez", () => {
    const onRetry = vi.fn();
    render(
      <OperationalIssuesModal
        open
        issues={[
          issue({
            issue_id: "HBI-FINALIZE-missing_mora_a_aplicar-j-0",
            stage: "finalize",
            title: "La revisión requiere correcciones.",
            user_message: "Falta Mora a aplicar.",
            location: {
              file_name: "rev.xlsx",
              sheet: "Distribucion_Pagos",
              row: 8,
              column: "Mora a aplicar",
              credit: "37",
              payment_id: null,
              client_name: "ACME",
            },
            next_action: "Complete Mora.",
            retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
            links: [
              {
                rel: "review_excel",
                label: "Abrir archivo de revisión",
                path: "/r.xlsx",
                web_url: "https://example.com/review.xlsx",
                open_mode: "sharepoint",
              },
            ],
            technical_reference: "job:j|code:missing_mora_a_aplicar",
          }),
          issue({
            issue_id: "HBI-FINALIZE-missing_abono_capital-j-1",
            stage: "finalize",
            title: "La revisión requiere correcciones.",
            user_message: "Falta Abono a capital.",
            location: {
              file_name: "rev.xlsx",
              sheet: "Distribucion_Pagos",
              row: 8,
              column: "Abono a capital",
              credit: "37",
              payment_id: null,
              client_name: "ACME",
            },
            next_action: "Complete Abono.",
            retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
            links: [
              {
                rel: "review_excel",
                label: "Abrir archivo de revisión",
                path: "/r.xlsx",
                web_url: "https://example.com/review.xlsx",
                open_mode: "sharepoint",
              },
            ],
            technical_reference: "job:j|code:missing_abono_capital",
          }),
          issue({
            issue_id: "HBI-FINALIZE-missing_otros_valores-j-2",
            stage: "finalize",
            title: "La revisión requiere correcciones.",
            user_message: "Faltan Otros valores.",
            location: {
              file_name: "rev.xlsx",
              sheet: "Distribucion_Pagos",
              row: 11,
              column: "Otros valores",
              credit: "40",
              payment_id: null,
              client_name: null,
            },
            next_action: "Complete Otros.",
            retry: { allowed: true, action: "finalize", label: "Verificar nuevamente" },
            links: [
              {
                rel: "review_excel",
                label: "Abrir archivo de revisión",
                path: "/r.xlsx",
                web_url: "https://example.com/review.xlsx",
                open_mode: "sharepoint",
              },
            ],
            technical_reference: "job:j|code:missing_otros_valores",
          }),
        ]}
        onClose={() => undefined}
        onRetryFor={() => onRetry}
      />,
    );
    expect(screen.getByRole("heading", { name: /Problemas operativos \(2\)/i })).toBeInTheDocument();
    expect(screen.getByText("Fila 8")).toBeInTheDocument();
    expect(screen.getByText("Fila 11")).toBeInTheDocument();
    expect(screen.getByText("Falta Mora a aplicar.")).toBeInTheDocument();
    expect(screen.getByText("Falta Abono a capital.")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: /Abrir archivo de revisión/i })).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Verificar nuevamente" })).toHaveLength(1);
  });

  it("modo formatRecovery: intro, checklist y CTA reconsolidar", async () => {
    const user = userEvent.setup();
    const onGo = vi.fn();
    render(
      <OperationalIssuesModal
        open
        title="Problemas de amortización"
        formatRecovery
        onGoReconsolidate={onGo}
        onClose={() => undefined}
        issues={[
          issue({
            issue_id: "amort-ACCOUNTING_PARSE_FAILED-264-0",
            stage: "amortization",
            title: "Documento contable · Crédito 264",
            user_message: "El PDF no tiene el formato esperado.",
            next_action: "Corrija y reconsolide.",
            technical_reference: "ACCOUNTING_PARSE_FAILED",
            links: [
              {
                rel: "asientos",
                label: "Abrir carpeta ASIENTOS",
                path: "clientes/X/ASIENTOS",
                web_url: "https://example.com/asientos",
                open_mode: "sharepoint",
              },
            ],
          }),
        ]}
      />,
    );
    expect(
      screen.getByText(/Corrija primero los PDF en SharePoint/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Ya reemplacé este PDF/i)).toBeInTheDocument();
    await user.click(screen.getByLabelText(/Ya reemplacé este PDF/i));
    expect(screen.getByLabelText(/Ya reemplacé este PDF/i)).toBeChecked();
    await user.click(
      screen.getByRole("button", {
        name: /Ya corregí los asientos — ir a reconsolidar/i,
      }),
    );
    expect(onGo).toHaveBeenCalled();
  });
});

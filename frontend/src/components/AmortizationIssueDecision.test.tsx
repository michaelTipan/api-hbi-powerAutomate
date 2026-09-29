import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AmortizationIssueDecision,
  type AmortizationDecisionHandlers,
} from "./AmortizationIssueDecision";
import { OperationalIssuesModal } from "./OperationalIssuesModal";
import type {
  UiAmortizationDecisions,
  UiIssueDecision,
  UiOperationalIssue,
} from "../types/contract";

function decision(overrides: Partial<UiIssueDecision> = {}): UiIssueDecision {
  return {
    excludable: true,
    group_credits: ["133"],
    group_key: "133",
    confirmable: false,
    conciliation_key: null,
    fecha_banco: "2026-07-31",
    bank_amount: 1000,
    asientos_amount: 1200,
    unapplied_amount: null,
    ...overrides,
  };
}

function issue(overrides: Partial<UiOperationalIssue> = {}): UiOperationalIssue {
  return {
    issue_id: "amort-CONCILIACION-133-0",
    stage: "amortization",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: "Consignación · Crédito 133",
    user_message: "Los asientos suman más que la consignación del banco.",
    location: {
      file_name: null,
      sheet: null,
      row: null,
      column: null,
      credit: "133",
      payment_id: "P1",
      client_name: "CLIENTE UNO",
    },
    value_found: null,
    expected_values: [],
    next_action: null,
    retry: null,
    links: [],
    technical_reference: "CONCILIACION_ASIENTOS_MAYOR_BANCO",
    decision: decision(),
    ...overrides,
  };
}

function decisions(overrides: Partial<UiAmortizationDecisions> = {}): UiAmortizationDecisions {
  return {
    available: true,
    user_message: null,
    excluded: [],
    confirmations: [],
    planned_lines: null,
    planned_tables: null,
    credits_not_amortized: [],
    ...overrides,
  };
}

function handlers(overrides: Partial<AmortizationDecisionHandlers> = {}): AmortizationDecisionHandlers {
  return {
    onExclude: vi.fn().mockResolvedValue(null),
    onUndoExclude: vi.fn().mockResolvedValue(null),
    onConfirm: vi.fn().mockResolvedValue(null),
    onUndoConfirm: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

const panel = <p>Detalle del problema</p>;

describe("AmortizationIssueDecision", () => {
  it("sin decisión posible muestra solo el panel (sin botones)", () => {
    render(
      <AmortizationIssueDecision
        issue={issue({ decision: null })}
        panel={panel}
        decisions={null}
        handlers={handlers()}
      />,
    );
    expect(screen.getByText("Detalle del problema")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("problema de todo el lote (no excluible) no ofrece Excluir crédito", () => {
    render(
      <AmortizationIssueDecision
        issue={issue({ decision: decision({ excludable: false }) })}
        panel={panel}
        decisions={null}
        handlers={handlers()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Excluir crédito" })).not.toBeInTheDocument();
  });

  it("excluir con motivo llama al handler con el código del motivo", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(
      <AmortizationIssueDecision issue={issue()} panel={panel} decisions={null} handlers={h} />,
    );
    await user.click(screen.getByRole("button", { name: "Excluir crédito" }));
    const excluir = screen.getByRole("button", { name: "Excluir" });
    expect(excluir).toBeDisabled();
    await user.click(screen.getByLabelText("Tabla de amortización con error"));
    expect(excluir).toBeEnabled();
    await user.click(excluir);
    expect(h.onExclude).toHaveBeenCalledWith("133", "TABLA_CON_ERROR", "");
  });

  it("«Otro (especificar)» exige texto antes de excluir", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(
      <AmortizationIssueDecision issue={issue()} panel={panel} decisions={null} handlers={h} />,
    );
    await user.click(screen.getByRole("button", { name: "Excluir crédito" }));
    await user.click(screen.getByLabelText("Otro (especificar)"));
    const excluir = screen.getByRole("button", { name: "Excluir" });
    expect(excluir).toBeDisabled();
    await user.type(screen.getByLabelText("Especifique el motivo"), "   ");
    expect(excluir).toBeDisabled();
    await user.type(screen.getByLabelText("Especifique el motivo"), "Cliente en acuerdo");
    await user.click(excluir);
    expect(h.onExclude).toHaveBeenCalledWith("133", "OTRO", "Cliente en acuerdo");
  });

  it("grupo con consignación compartida avisa que se excluirán ambos", async () => {
    const user = userEvent.setup();
    render(
      <AmortizationIssueDecision
        issue={issue({ decision: decision({ group_credits: ["102", "133"] }) })}
        panel={panel}
        decisions={null}
        handlers={handlers()}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Excluir crédito" }));
    expect(
      screen.getByText(
        "El crédito 133 comparte consignación con el crédito 102. Se excluirán ambos.",
      ),
    ).toBeInTheDocument();
  });

  it("error del servidor se muestra en línea y el formulario sigue abierto", async () => {
    const user = userEvent.setup();
    const h = handlers({
      onExclude: vi.fn().mockResolvedValue("El proceso ya fue procesado."),
    });
    render(
      <AmortizationIssueDecision issue={issue()} panel={panel} decisions={null} handlers={h} />,
    );
    await user.click(screen.getByRole("button", { name: "Excluir crédito" }));
    await user.click(screen.getByLabelText("Se aplicará manualmente"));
    await user.click(screen.getByRole("button", { name: "Excluir" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("El proceso ya fue procesado.");
    expect(screen.getByRole("button", { name: "Excluir" })).toBeInTheDocument();
  });

  it("crédito excluido: recuadro neutro con motivo y Deshacer", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(
      <AmortizationIssueDecision
        issue={issue()}
        panel={panel}
        decisions={decisions({
          excluded: [
            {
              credit: "133",
              client_name: "CLIENTE UNO",
              motivo: "Falta el asiento de Contabilidad",
              motivo_codigo: "FALTA_ASIENTO",
              nota: null,
              group_credits: ["133"],
              exclusion_id: "e1",
              can_undo: true,
              table_link: null,
            },
          ],
        })}
        handlers={h}
      />,
    );
    expect(screen.getByText(/Excluido · Falta el asiento de Contabilidad/)).toBeInTheDocument();
    expect(screen.queryByText("Detalle del problema")).not.toBeInTheDocument();
    expect(screen.queryByText("FALTA_ASIENTO")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(h.onUndoExclude).toHaveBeenCalledWith("133");
  });

  it("tras Procesar (bloqueado) el excluido no ofrece Deshacer", () => {
    render(
      <AmortizationIssueDecision
        issue={issue()}
        panel={panel}
        decisions={decisions({
          excluded: [
            {
              credit: "133",
              client_name: null,
              motivo: "Se aplicará manualmente",
              motivo_codigo: "APLICACION_MANUAL",
              nota: null,
              group_credits: ["133"],
              exclusion_id: "e1",
              can_undo: false,
              table_link: null,
            },
          ],
        })}
        handlers={handlers()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Deshacer" })).not.toBeInTheDocument();
  });

  it("Continuar con los asientos (con nota opcional) y luego Deshacer", async () => {
    const user = userEvent.setup();
    const h = handlers();
    const confirmable = issue({
      technical_reference: "CONCILIACION_BANCO_MAYOR_ASIENTOS",
      decision: decision({
        excludable: true,
        confirmable: true,
        conciliation_key: "P1|2026-07-31|133",
        bank_amount: 1004,
        asientos_amount: 1000,
        unapplied_amount: 4,
      }),
    });
    const { rerender } = render(
      <AmortizationIssueDecision issue={confirmable} panel={panel} decisions={null} handlers={h} />,
    );
    await user.click(screen.getByRole("button", { name: "Agregar nota" }));
    await user.type(screen.getByLabelText("Nota (opcional)"), "Saldo a favor del cliente");
    await user.click(screen.getByRole("button", { name: "Continuar con los asientos" }));
    expect(h.onConfirm).toHaveBeenCalledWith("P1|2026-07-31|133", "Saldo a favor del cliente");

    rerender(
      <AmortizationIssueDecision
        issue={confirmable}
        panel={panel}
        decisions={decisions({
          confirmations: [
            {
              conciliation_key: "P1|2026-07-31|133",
              credits: ["133"],
              fecha_banco: "2026-07-31",
              bank_amount: 1004,
              asientos_amount: 1000,
              unapplied_amount: 4,
              nota: "Saldo a favor del cliente",
              can_undo: true,
            },
          ],
        })}
        handlers={h}
      />,
    );
    expect(screen.getByText(/Continuar con los asientos · \$4 sin aplicar/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Deshacer" }));
    expect(h.onUndoConfirm).toHaveBeenCalledWith("P1|2026-07-31|133");
  });

  it("disabled bloquea todas las acciones", () => {
    render(
      <AmortizationIssueDecision
        issue={issue()}
        panel={panel}
        decisions={null}
        handlers={handlers()}
        disabled
      />,
    );
    expect(screen.getByRole("button", { name: "Excluir crédito" })).toBeDisabled();
  });
});

describe("OperationalIssuesModal con renderIssue", () => {
  it("el modal sigue abierto tras excluir y el título cuenta solo pendientes", async () => {
    const user = userEvent.setup();
    const h = handlers();
    const onClose = vi.fn();
    render(
      <OperationalIssuesModal
        open
        title="Problemas de amortización"
        issues={[issue()]}
        titleCount={0}
        onClose={onClose}
        renderIssue={(i, p) => (
          <AmortizationIssueDecision issue={i} panel={p} decisions={null} handlers={h} />
        )}
      />,
    );
    const dialog = screen.getByRole("dialog");
    expect(
      within(dialog).getByRole("heading", { name: /Problemas de amortización \(0\)/ }),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito" }));
    await user.click(within(dialog).getByLabelText("Falta el asiento de Contabilidad"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir" }));
    expect(h.onExclude).toHaveBeenCalledWith("133", "FALTA_ASIENTO", "");
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MergeCreditReviewModal } from "./MergeCreditReviewModal";
import { asiento, fecha, group, handlers, twoPaymentGroup } from "../mocks/mergeVerification";
import type { UiMergeGroup } from "../types/contract";

const FOLDERS = [{ credito: "102", web_url: "https://example.com/asientos-102" }];

function renderModal(
  g: UiMergeGroup,
  h = handlers(),
  extra: { onOpenAssignment?: () => void } = {},
) {
  const onClose = vi.fn();
  render(
    <MergeCreditReviewModal
      group={g}
      handlers={h}
      folderLinks={FOLDERS}
      onClose={onClose}
      onOpenAssignment={extra.onOpenAssignment}
    />,
  );
  return { h, onClose, dialog: screen.getByRole("dialog") };
}

/** Banco recibió más que los asientos (p. ej. diferencia de $4). */
function bankGreaterGroup(overrides: Partial<UiMergeGroup> = {}): UiMergeGroup {
  return group({
    status: "attention",
    motivos: [{ code: "DIFERENCIA_BANCO", label: "Diferencia con el banco" }],
    primary_action: "revisar",
    consignado: 104,
    segun_asientos: 100,
    pendiente: 4,
    fechas: [fecha({ monto_banco: 104, monto_asientos: 100, diferencia: 4, status: "BANK_GREATER" })],
    actions: { continuar: true, no_corresponde: true, asignar: false, excluir: true },
    ...overrides,
  });
}

describe("MergeCreditReviewModal", () => {
  it("muestra consignaciones y asientos; retenciones y saldos solo si existen", () => {
    const { dialog } = renderModal(group());
    expect(within(dialog).getByRole("heading", { name: "Consignaciones" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "Tipo de aplicación" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("columnheader", { name: "Concepto" })).not.toBeInTheDocument();
    expect(within(dialog).getByText("PAGO CUOTA")).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "Número" })).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "Valor del asiento" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("columnheader", { name: "Recibido en banco" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("columnheader", { name: "Pago" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Excluir crédito/ })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("columnheader", { name: "Retenciones" })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("columnheader", { name: "Saldos menores" })).not.toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Ver PDF" })).toHaveAttribute(
      "href",
      "https://example.com/a-1.pdf",
    );
  });

  it("con retenciones y saldos menores agrega sus columnas", () => {
    const { dialog } = renderModal(
      group({
        has_retenciones: true,
        has_saldos_menores: true,
        asientos: [asiento({ retenciones: 2516, saldos_menores: 4 })],
      }),
    );
    expect(within(dialog).getByRole("columnheader", { name: "Retenciones" })).toBeInTheDocument();
    expect(within(dialog).getByText("$2.516")).toBeInTheDocument();
    expect(within(dialog).getByRole("columnheader", { name: "Saldos menores" })).toBeInTheDocument();
  });

  it("Continuar con los asientos guarda la confirmación con la nota", async () => {
    const user = userEvent.setup();
    const { dialog, h } = renderModal(bankGreaterGroup());
    await user.type(within(dialog).getByLabelText("Nota (opcional)"), "Redondeo del banco");
    await user.click(within(dialog).getByRole("button", { name: "Continuar con los asientos" }));
    await waitFor(() =>
      expect(h.onConfirm).toHaveBeenCalledWith("102|2026-09-22", "Redondeo del banco"),
    );
  });

  it("Deshacer una confirmación", async () => {
    const user = userEvent.setup();
    const g = bankGreaterGroup({
      status: "ready",
      motivos: [],
      fechas: [
        fecha({
          monto_banco: 104,
          monto_asientos: 100,
          diferencia: 4,
          status: "CONFIRMED",
          confirmation: { nota: null, can_undo: true },
        }),
      ],
    });
    const { dialog, h } = renderModal(g);
    expect(within(dialog).getByText(/\$4 sin aplicar/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(h.onUndoConfirm).toHaveBeenCalledWith("102|2026-09-22"));
  });

  it("No corresponde a este pago usa el motivo del estado del asiento", async () => {
    const user = userEvent.setup();
    const g = group({
      status: "attention",
      motivos: [{ code: "ASIENTO_OTRO_CREDITO", label: "Asiento de otro crédito" }],
      asientos: [
        asiento({ state: "otro_credito", state_label: "Asiento de otro crédito (No. Rad 250)" }),
      ],
    });
    const { dialog, h } = renderModal(g);
    await user.click(within(dialog).getByRole("button", { name: "No corresponde a este pago" }));
    await waitFor(() =>
      expect(h.onMarkUnused).toHaveBeenCalledWith("ASIENTOS/102/A-1.pdf", "OTRO_CREDITO"),
    );
  });

  it("Deshacer un asiento marcado como no correspondiente", async () => {
    const user = userEvent.setup();
    const g = group({
      asientos: [
        asiento({
          state: "no_usado",
          state_label: "No corresponde a este pago",
          can_mark_unused: false,
          can_undo_unused: true,
        }),
      ],
    });
    const { dialog, h } = renderModal(g);
    await user.click(within(dialog).getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(h.onUndoUnused).toHaveBeenCalledWith("ASIENTOS/102/A-1.pdf"));
  });

  it("falta el asiento: abrir carpeta y verificar de nuevo", async () => {
    const user = userEvent.setup();
    const g = group({
      status: "attention",
      motivos: [{ code: "FALTA_ASIENTO", label: "Falta el asiento" }],
      asientos: [],
      segun_asientos: 0,
      pendiente: 100,
      actions: { continuar: false, no_corresponde: false, asignar: false, excluir: true },
    });
    const { dialog, h } = renderModal(g);
    expect(within(dialog).getByText("No hay asientos en la carpeta del crédito.")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Abrir carpeta de asientos" })).toHaveAttribute(
      "href",
      "https://example.com/asientos-102",
    );
    await user.click(within(dialog).getByRole("button", { name: "Verificar de nuevo" }));
    expect(h.onVerify).toHaveBeenCalled();
  });

  it("no pide confirmar el tipo: solo muestra el tipo de aplicación del Excel de revisión", () => {
    const { dialog } = renderModal(twoPaymentGroup());
    const rows = within(dialog).getAllByRole("row").map((r) => r.textContent ?? "");
    expect(rows.some((t) => t.includes("22/09") && t.includes("ABONO A CAPITAL"))).toBe(true);
    expect(rows.some((t) => t.includes("25/09") && t.includes("PAGO CUOTA"))).toBe(true);
    expect(within(dialog).queryByText(/Tipo usado|Tipo declarado|según los asientos:/)).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Usar el tipo/ })).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Nota (obligatoria)")).not.toBeInTheDocument();
  });

  it("Continuar con los asientos no exige nota", async () => {
    const user = userEvent.setup();
    const { dialog, h } = renderModal(bankGreaterGroup());
    await user.click(within(dialog).getByRole("button", { name: "Continuar con los asientos" }));
    await waitFor(() => expect(h.onConfirm).toHaveBeenCalledWith("102|2026-09-22", ""));
  });

  it("Excluir crédito con los mismos motivos de la fase 4 y Deshacer", async () => {
    const user = userEvent.setup();
    const { dialog, h } = renderModal(bankGreaterGroup());
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito 102" }));
    expect(
      within(dialog).getByRole("group", { name: "Excluir crédito 102 · CLIENTE SINTETICO" }),
    ).toBeInTheDocument();
    for (const label of [
      "Falta el asiento de Contabilidad",
      "Asiento con error, pendiente de corrección",
      "Tabla de amortización con error",
      "Se aplicará manualmente",
      "Otro (especificar)",
    ]) {
      expect(within(dialog).getByLabelText(label)).toBeInTheDocument();
    }
    await user.click(within(dialog).getByLabelText("Se aplicará manualmente"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito 102" }));
    await waitFor(() => expect(h.onExclude).toHaveBeenCalledWith("102", "APLICACION_MANUAL", ""));
  });

  it("crédito excluido: muestra el motivo y permite Deshacer", async () => {
    const user = userEvent.setup();
    const g = bankGreaterGroup({
      status: "excluded",
      exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
    });
    const { dialog, h } = renderModal(g);
    expect(within(dialog).getByText(/Se aplicará manualmente/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Continuar con los asientos" })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Deshacer" }));
    await waitFor(() => expect(h.onUndoExclude).toHaveBeenCalledWith("102"));
  });

  it("registro de decisiones ilegible: mensaje visible y la ventana se puede cerrar", async () => {
    const user = userEvent.setup();
    const msg =
      "No pudimos leer las decisiones guardadas del proceso. Intente de nuevo; si continúa, contacte a soporte.";
    const h = handlers({ onConfirm: vi.fn().mockResolvedValue(msg) });
    const { dialog, onClose } = renderModal(bankGreaterGroup(), h);
    await user.click(within(dialog).getByRole("button", { name: "Continuar con los asientos" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(msg);
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("conflicto 409: el mensaje se muestra y las acciones siguen disponibles", async () => {
    const user = userEvent.setup();
    const msg = "Hay una consolidación en curso. Espere a que termine e intente de nuevo.";
    const h = handlers({ onMarkUnused: vi.fn().mockResolvedValue(msg) });
    const { dialog } = renderModal(bankGreaterGroup(), h);
    await user.click(within(dialog).getByRole("button", { name: "No corresponde a este pago" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(msg);
    expect(within(dialog).getByRole("button", { name: "No corresponde a este pago" })).toBeEnabled();
  });

  it("asignación pendiente: abre la ventana Asignar desde Revisar", async () => {
    const user = userEvent.setup();
    const onOpenAssignment = vi.fn();
    const { dialog } = renderModal(twoPaymentGroup(), handlers(), { onOpenAssignment });
    await user.click(within(dialog).getByRole("button", { name: "Asignar asientos a sus pagos" }));
    expect(onOpenAssignment).toHaveBeenCalled();
  });

  it("con asignación guardada ofrece «Modificar asignación»", () => {
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({ assignment: { ...base.assignment!, explicit: true, can_undo: true } });
    const { dialog } = renderModal(g, handlers(), { onOpenAssignment: vi.fn() });
    expect(within(dialog).getByRole("button", { name: "Modificar asignación" })).toBeInTheDocument();
  });

  it("GIRALDO 209: listo con pagos del 15/09 y 30/09 muestra a qué pago va cada asiento y deja modificar", async () => {
    const user = userEvent.setup();
    const onOpenAssignment = vi.fn();
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      group_key: "209",
      credits: ["209"],
      cliente: "GIRALDO",
      status: "ready",
      motivos: [],
      primary_action: null,
      consignaciones: [
        { id_pago: "P15", fecha: "2026-09-15", monto: 100, tipo: "PAGO CUOTA", credits: ["209"], label: "15/09 · $100", kind: "pago" },
        { id_pago: "P30", fecha: "2026-09-30", monto: 50, tipo: "ABONO A CAPITAL", credits: ["209"], label: "30/09 · $50", kind: "abono" },
      ],
      asientos: [
        asiento({ path: "A/209-15.pdf", numero: "5101", fecha: "2026-09-15", cash: 100, assigned_id_pago: "P15" }),
        asiento({ path: "A/209-30.pdf", numero: "5102", fecha: "2026-09-30", cash: 50, assigned_id_pago: "P30" }),
      ],
      assignment: { ...base.assignment!, required: false },
      actions: { continuar: false, no_corresponde: true, asignar: true, excluir: false },
    });
    const { dialog } = renderModal(g, handlers(), { onOpenAssignment });
    expect(within(dialog).getByRole("columnheader", { name: "Pago" })).toBeInTheDocument();
    const rows = within(dialog).getAllByRole("row").map((r) => r.textContent ?? "");
    expect(rows.some((t) => t.includes("5101") && t.includes("Pago del 15/09/2026"))).toBe(true);
    expect(rows.some((t) => t.includes("5102") && t.includes("Abono del 30/09/2026"))).toBe(true);
    expect(within(dialog).queryByRole("button", { name: /Excluir crédito/ })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Modificar asignación" }));
    expect(onOpenAssignment).toHaveBeenCalled();
  });

  it("asiento sin valores legibles: no corresponde, abrir carpeta, verificar de nuevo y excluir", async () => {
    const user = userEvent.setup();
    const g = group({
      status: "attention",
      motivos: [{ code: "ASIENTO_SIN_VALORES", label: "No se pudieron leer los valores del asiento" }],
      primary_action: "revisar",
      segun_asientos: null,
      pendiente: null,
      fechas: [],
      asientos: [asiento({ state: "sin_datos", state_label: "No se pudieron leer los valores", cash: null })],
      actions: { continuar: false, no_corresponde: true, asignar: false, excluir: true },
    });
    const { dialog, h } = renderModal(g);
    expect(within(dialog).getByRole("button", { name: "No corresponde a este pago" })).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Abrir carpeta de asientos" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Excluir crédito 102" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Verificar de nuevo" }));
    expect(h.onVerify).toHaveBeenCalled();
  });
});

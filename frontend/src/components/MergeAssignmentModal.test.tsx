import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MergeAssignmentModal } from "./MergeAssignmentModal";
import { asiento, assignment, handlers, twoPaymentGroup } from "../mocks/mergeVerification";
import { MSG_IMPOSSIBLE, MSG_SHORTFALL, MSG_TIE } from "../domain/mergeVerification";

const FOLDERS = [{ credito: "133", web_url: "https://example.com/asientos-133" }];

function renderModal(g = twoPaymentGroup(), h = handlers(), onClose = vi.fn()) {
  render(<MergeAssignmentModal group={g} handlers={h} folderLinks={FOLDERS} onClose={onClose} />);
  return { h, onClose, dialog: screen.getByRole("dialog") };
}

function tieGroup() {
  const base = twoPaymentGroup();
  return twoPaymentGroup({
    assignment: assignment({ tie: true, proposal: {}, payments: base.assignment!.payments }),
  });
}

describe("MergeAssignmentModal", () => {
  it("muestra la tabla con fecha del asiento, recibido en banco, pago y PDF", () => {
    const { dialog } = renderModal();
    for (const h of ["Asiento", "Fecha del asiento", "Recibido en banco", "Pago", "PDF"]) {
      expect(within(dialog).getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    const select = within(dialog).getByLabelText("Pago del asiento 2001") as HTMLSelectElement;
    expect(select.value).toBe("P1");
    expect(within(select).getByRole("option", { name: "22/09 · $100" })).toBeInTheDocument();
    expect(within(dialog).getAllByRole("link", { name: "Ver PDF" })).toHaveLength(2);
    const summary = within(dialog).getByRole("list", { name: "Resumen por pago" });
    expect(within(summary).getByText("Pago 22/09 $100 · Asignado $100 · Cuadra")).toBeInTheDocument();
  });

  it("asignación pendiente: Confirmar deshabilitado hasta asignar todos los asientos", async () => {
    const user = userEvent.setup();
    const { dialog, h, onClose } = renderModal(tieGroup());
    expect(within(dialog).getByText(MSG_TIE)).toBeInTheDocument();
    const selA = within(dialog).getByLabelText("Pago del asiento 2001") as HTMLSelectElement;
    const selB = within(dialog).getByLabelText("Pago del asiento 2002") as HTMLSelectElement;
    expect(selA.value).toBe("");
    expect(within(selA).getByRole("option", { name: "Seleccione" })).toBeInTheDocument();
    const confirm = within(dialog).getByRole("button", { name: "Confirmar" });
    expect(confirm).toBeDisabled();
    await user.selectOptions(selA, "P1");
    expect(confirm).toBeDisabled();
    await user.selectOptions(selB, "P2");
    expect(confirm).toBeEnabled();
    await user.click(confirm);
    await waitFor(() =>
      expect(h.onAssign).toHaveBeenCalledWith("133", [
        { asiento_path: "ASIENTOS/133/A.pdf", id_pago: "P1" },
        { asiento_path: "ASIENTOS/133/B.pdf", id_pago: "P2" },
      ]),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("un pago excedido deshabilita Confirmar y muestra «Sobran»", async () => {
    const user = userEvent.setup();
    const { dialog } = renderModal();
    await user.selectOptions(within(dialog).getByLabelText("Pago del asiento 2001"), "P2");
    await user.selectOptions(within(dialog).getByLabelText("Pago del asiento 2002"), "P1");
    expect(within(dialog).getByText("Pago 25/09 $50 · Asignado $100 · Sobran $50")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Confirmar" })).toBeDisabled();
  });

  it("un faltante permite confirmar y avisa que queda como «Diferencia no aplicada»", () => {
    const g = twoPaymentGroup({
      asientos: [
        asiento({ path: "ASIENTOS/133/A.pdf", credito: "133", numero: "2001", cash: 90, eligible_id_pagos: ["P1"] }),
        asiento({ path: "ASIENTOS/133/B.pdf", credito: "133", numero: "2002", cash: 50, eligible_id_pagos: ["P1", "P2"] }),
      ],
    });
    const { dialog } = renderModal(g);
    expect(within(dialog).getByText("Pago 22/09 $100 · Asignado $90 · Faltan $10")).toBeInTheDocument();
    expect(within(dialog).getByText(MSG_SHORTFALL)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Confirmar" })).toBeEnabled();
  });

  it("solo ofrece pagos con fecha ≤ fecha del asiento", () => {
    const g = twoPaymentGroup({
      asientos: [
        asiento({ path: "ASIENTOS/133/A.pdf", credito: "133", numero: "2001", fecha: "2026-09-23", cash: 100, eligible_id_pagos: ["P1"] }),
        asiento({ path: "ASIENTOS/133/B.pdf", credito: "133", numero: "2002", cash: 50, eligible_id_pagos: ["P1", "P2"] }),
      ],
    });
    const { dialog } = renderModal(g);
    const selA = within(dialog).getByLabelText("Pago del asiento 2001");
    expect(within(selA).queryByRole("option", { name: "25/09 · $50" })).not.toBeInTheDocument();
    expect(within(selA).getByRole("option", { name: "22/09 · $100" })).toBeInTheDocument();
  });

  it("un asiento ya aplicado se muestra en gris sin selector", () => {
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      asientos: [
        ...base.asientos,
        asiento({
          path: "ASIENTOS/133/OLD.pdf",
          credito: "133",
          numero: "1990",
          state: "ya_aplicado",
          state_label: "Ya aplicado el 10/09",
          eligible_id_pagos: [],
        }),
      ],
    });
    const { dialog } = renderModal(g);
    const row = within(dialog).getByText("1990").closest("tr") as HTMLElement;
    expect(row).toHaveClass("is-muted");
    expect(within(row).getByText("Ya aplicado el 10/09")).toBeInTheDocument();
    expect(within(row).queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("error al guardar: se muestra y la ventana sigue abierta con Cerrar disponible", async () => {
    const user = userEvent.setup();
    const h = handlers({ onAssign: vi.fn().mockResolvedValue("No pudimos guardar la decisión.") });
    const { dialog, onClose } = renderModal(twoPaymentGroup(), h);
    await user.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("No pudimos guardar la decisión.");
    expect(onClose).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Cerrar" })).toBeEnabled();
  });

  it("conflicto 409 (otra operación en curso): mensaje visible y se puede reintentar", async () => {
    const user = userEvent.setup();
    const busyMsg = "Hay una consolidación en curso. Espere a que termine e intente de nuevo.";
    const onAssign = vi.fn().mockResolvedValueOnce(busyMsg).mockResolvedValueOnce(null);
    const { dialog, onClose } = renderModal(twoPaymentGroup(), handlers({ onAssign }));
    await user.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(busyMsg);
    await user.click(within(dialog).getByRole("button", { name: "Confirmar" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onAssign).toHaveBeenCalledTimes(2);
  });

  it("asignación imposible: explica, ofrece carpeta, Cerrar y Excluir; sin Confirmar", async () => {
    const user = userEvent.setup();
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      assignment: assignment({ impossible: true, payments: base.assignment!.payments }),
    });
    const { dialog, h, onClose } = renderModal(g);
    expect(within(dialog).getByText(MSG_IMPOSSIBLE)).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Abrir carpeta de asientos" })).toHaveAttribute(
      "href",
      "https://example.com/asientos-133",
    );
    expect(within(dialog).queryByRole("button", { name: "Confirmar" })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Excluir crédito" }));
    await user.click(within(dialog).getByLabelText("Falta el asiento de Contabilidad"));
    await user.click(within(dialog).getByRole("button", { name: "Excluir" }));
    await waitFor(() => expect(h.onExclude).toHaveBeenCalledWith("133", "FALTA_ASIENTO", ""));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("Cerrar sale sin guardar", async () => {
    const user = userEvent.setup();
    const { dialog, h, onClose } = renderModal();
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(onClose).toHaveBeenCalled();
    expect(h.onAssign).not.toHaveBeenCalled();
  });

  it("Deshacer asignación llama al endpoint", async () => {
    const user = userEvent.setup();
    const base = twoPaymentGroup();
    const g = twoPaymentGroup({
      assignment: { ...base.assignment!, explicit: true, can_undo: true },
      asientos: base.asientos.map((a, i) => ({ ...a, assigned_id_pago: i === 0 ? "P1" : "P2" })),
    });
    const { dialog, h } = renderModal(g);
    await user.click(within(dialog).getByRole("button", { name: "Deshacer asignación" }));
    await waitFor(() => expect(h.onUndoAssign).toHaveBeenCalledWith("133"));
  });
});

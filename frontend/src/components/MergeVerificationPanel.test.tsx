import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MergeVerificationPanel } from "./MergeVerificationPanel";
import { group, handlers, twoPaymentGroup, verification } from "../mocks/mergeVerification";

const FOLDERS = [{ credito: "133", web_url: "https://example.com/asientos-133" }];

function missingGroup() {
  return group({
    group_key: "247",
    credits: ["247"],
    clientes: { "247": "CLIENTE FALTANTE" },
    cliente: "CLIENTE FALTANTE",
    status: "attention",
    motivos: [{ code: "FALTA_ASIENTO", label: "Falta el asiento" }],
    primary_action: "revisar",
    consignado: 100,
    segun_asientos: 0,
    pendiente: 100,
    asientos: [],
    actions: { continuar: false, no_corresponde: false, asignar: false, tipo: false, excluir: true },
  });
}

function excludedGroup() {
  return group({
    group_key: "95",
    credits: ["95"],
    clientes: { "95": "TRANSPORTES SINTETICO" },
    cliente: "TRANSPORTES SINTETICO",
    status: "excluded",
    exclusion: { motivo: "Se aplicará manualmente", motivo_codigo: "APLICACION_MANUAL", can_undo: true },
  });
}

function renderPanel(v = verification([group(), missingGroup(), twoPaymentGroup(), excludedGroup()])) {
  const h = handlers();
  render(<MergeVerificationPanel verification={v} handlers={h} folderLinks={FOLDERS} />);
  return { h };
}

describe("MergeVerificationPanel", () => {
  it("resumen y tabla «Requieren atención» solo con los créditos pendientes", () => {
    renderPanel();
    expect(screen.getByRole("status")).toHaveTextContent("1 de 4 créditos listos para consolidar.");
    expect(screen.getByRole("heading", { name: "Requieren atención" })).toBeInTheDocument();
    for (const h of ["Cliente", "Crédito", "Consignado", "Según asientos", "Pendiente"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    const table = screen.getByRole("table");
    expect(within(table).getByText("CLIENTE FALTANTE")).toBeInTheDocument();
    expect(within(table).getByText("Falta el asiento")).toBeInTheDocument();
    expect(within(table).getByText("CLIENTE DOS FECHAS")).toBeInTheDocument();
    expect(within(table).queryByText("CLIENTE SINTETICO")).not.toBeInTheDocument();
    expect(screen.getByText(/Excluido: crédito 95 · TRANSPORTES SINTETICO/)).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/FALTA_ASIENTO|ASIGNAR_ASIENTOS|attention/);
  });

  it("«Ver todos los créditos» muestra también los listos", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole("button", { name: "Ver todos los créditos" }));
    expect(screen.getByRole("heading", { name: "Todos los créditos" })).toBeInTheDocument();
    const table = screen.getByRole("table");
    expect(within(table).getByText("CLIENTE SINTETICO")).toBeInTheDocument();
    expect(within(table).getByText("Listo")).toBeInTheDocument();
  });

  it("Asignar abre la ventana de asignación y Cerrar vuelve al panel", async () => {
    const user = userEvent.setup();
    renderPanel();
    const row = screen.getByText("CLIENTE DOS FECHAS").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Asignar" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Asignar asientos · Crédito 133/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Revisar abre la ventana del crédito", async () => {
    const user = userEvent.setup();
    renderPanel();
    const row = screen.getByText("CLIENTE FALTANTE").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisar" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Consignaciones" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Excluir crédito" })).toBeInTheDocument();
  });

  it("desde Revisar se puede pasar a Asignar", async () => {
    const user = userEvent.setup();
    renderPanel();
    const row = screen.getByText("CLIENTE DOS FECHAS").closest("tr") as HTMLElement;
    await user.click(within(row).getByRole("button", { name: "Revisar" }));
    await user.click(screen.getByRole("button", { name: "Asignar asientos a sus pagos" }));
    expect(screen.getByText(/Asignar asientos · Crédito 133/)).toBeInTheDocument();
  });

  it("Verificar de nuevo vuelve a leer las carpetas", async () => {
    const user = userEvent.setup();
    const { h } = renderPanel();
    await user.click(screen.getByRole("button", { name: "Verificar de nuevo" }));
    expect(h.onVerify).toHaveBeenCalled();
  });

  it("todos excluidos: indica cómo salir", () => {
    renderPanel(verification([excludedGroup()]));
    expect(
      screen.getByText("Todos los créditos están excluidos. Deshaga una exclusión para consolidar o cancele el proceso."),
    ).toBeInTheDocument();
  });
});

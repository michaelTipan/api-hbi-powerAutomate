import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MergeVerificationSummary, MergeVerificationTable } from "./MergeVerificationPanel";
import { group, handlers, twoPaymentGroup, verification } from "../mocks/mergeVerification";

const FOLDERS = [
  { credito: "133", web_url: "https://example.com/asientos-133" },
  { credito: "247", web_url: "https://example.com/asientos-247" },
];

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
    actions: { continuar: false, no_corresponde: false, asignar: false, excluir: true },
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

function allGroups() {
  return verification([group(), excludedGroup(), missingGroup(), twoPaymentGroup()]);
}

function renderTable(v = allGroups()) {
  const h = handlers();
  render(<MergeVerificationTable verification={v} handlers={h} folderLinks={FOLDERS} />);
  return { h };
}

function rowOf(text: string): HTMLElement {
  return screen.getByText(text).closest("tr") as HTMLElement;
}

describe("MergeVerificationSummary", () => {
  it("resumen y Verificar de nuevo", async () => {
    const user = userEvent.setup();
    const h = handlers();
    render(<MergeVerificationSummary verification={allGroups()} handlers={h} />);
    expect(screen.getByRole("status")).toHaveTextContent("1 de 4 créditos listos para consolidar.");
    await user.click(screen.getByRole("button", { name: "Verificar de nuevo" }));
    expect(h.onVerify).toHaveBeenCalled();
  });

  it("todos excluidos: indica cómo salir", () => {
    render(<MergeVerificationSummary verification={verification([excludedGroup()])} handlers={handlers()} />);
    expect(
      screen.getByText("Todos los créditos están excluidos. Deshaga una exclusión para consolidar o cancele el proceso."),
    ).toBeInTheDocument();
  });
});

describe("MergeVerificationTable", () => {
  it("muestra todos los créditos al entrar: primero los que requieren atención y al final los excluidos", () => {
    renderTable();
    for (const h of ["Cliente", "Crédito", "Estado", "Consignado", "Según asientos", "Diferencia", "Asientos"]) {
      expect(screen.getByRole("columnheader", { name: h })).toBeInTheDocument();
    }
    expect(screen.queryByRole("columnheader", { name: "Pendiente" })).not.toBeInTheDocument();
    const clients = within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((r) => r.querySelector("td")?.textContent);
    expect(clients).toEqual(["CLIENTE FALTANTE", "CLIENTE DOS FECHAS", "CLIENTE SINTETICO", "TRANSPORTES SINTETICO"]);
    expect(screen.queryByRole("button", { name: /Ver todos los créditos|Ver solo/ })).not.toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/FALTA_ASIENTO|ASIGNAR_ASIENTOS|attention|excluded/);
  });

  it("estado con chips de color y en palabras", () => {
    renderTable();
    const chip = (row: string, label: string) => within(rowOf(row)).getByText(label);
    expect(chip("CLIENTE SINTETICO", "Listo")).toHaveClass("merge-status-chip", "ok");
    expect(chip("CLIENTE FALTANTE", "Falta el asiento")).toHaveClass("merge-status-chip", "danger");
    expect(chip("CLIENTE DOS FECHAS", "Asignar asientos")).toHaveClass("merge-status-chip", "warn");
    expect(chip("TRANSPORTES SINTETICO", "Excluido")).toHaveClass("merge-status-chip", "muted");
    expect(within(rowOf("TRANSPORTES SINTETICO")).getByText("Se aplicará manualmente")).toBeInTheDocument();
    expect(rowOf("TRANSPORTES SINTETICO")).toHaveClass("is-muted");
  });

  it("cada fila abre su carpeta de asientos", () => {
    renderTable();
    expect(within(rowOf("CLIENTE FALTANTE")).getByRole("link", { name: "Abrir carpeta" })).toHaveAttribute(
      "href",
      "https://example.com/asientos-247",
    );
    expect(within(rowOf("CLIENTE DOS FECHAS")).getByRole("link", { name: "Abrir carpeta" })).toHaveAttribute(
      "href",
      "https://example.com/asientos-133",
    );
    expect(within(rowOf("CLIENTE SINTETICO")).queryByRole("link")).not.toBeInTheDocument();
  });

  it("montos sin salto de línea y acción en columna fija", () => {
    renderTable();
    const row = rowOf("CLIENTE FALTANTE");
    const cells = within(row).getAllByRole("cell");
    expect(cells[3]).toHaveClass("nowrap");
    expect(cells[5]).toHaveClass("nowrap");
    expect(cells[cells.length - 1]).toHaveClass("merge-action-col");
  });

  it("Asignar abre la ventana de asignación y Cerrar vuelve a la tabla", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(within(rowOf("CLIENTE DOS FECHAS")).getByRole("button", { name: "Asignar" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Asignar asientos · Crédito 133/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("Revisar abre la ventana del crédito", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(within(rowOf("CLIENTE FALTANTE")).getByRole("button", { name: "Revisar" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "Consignaciones" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Excluir crédito" })).toBeInTheDocument();
  });

  it("un excluido se puede revisar para deshacer la exclusión", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(within(rowOf("TRANSPORTES SINTETICO")).getByRole("button", { name: "Revisar" }));
    expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Deshacer" })).toBeInTheDocument();
  });

  it("desde Revisar se puede pasar a Asignar", async () => {
    const user = userEvent.setup();
    renderTable();
    await user.click(within(rowOf("CLIENTE DOS FECHAS")).getByRole("button", { name: "Revisar" }));
    await user.click(screen.getByRole("button", { name: "Asignar asientos a sus pagos" }));
    expect(screen.getByText(/Asignar asientos · Crédito 133/)).toBeInTheDocument();
  });
});

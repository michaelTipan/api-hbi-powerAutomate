import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("deshabilita confirmar cuando confirmDisabled es true", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <ConfirmDialog
        title="Confirmar"
        confirmLabel="Confirmar envío"
        confirmDisabled
        confirmDisabledTitle="Espere la lectura"
        onConfirm={onConfirm}
        onCancel={onCancel}
      >
        <p>Leyendo…</p>
      </ConfirmDialog>,
    );
    const confirmBtn = screen.getByRole("button", { name: /Confirmar envío/i });
    expect(confirmBtn).toBeDisabled();
    expect(confirmBtn).toHaveAttribute("title", "Espere la lectura");
    await userEvent.click(confirmBtn);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("coloca Cancelar a la izquierda y el primary a la derecha", () => {
    render(
      <ConfirmDialog
        title="Confirmar"
        confirmLabel="Procesar amortización"
        onConfirm={() => undefined}
        onCancel={() => undefined}
      >
        <p>Detalle</p>
      </ConfirmDialog>,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveTextContent(/^Cancelar$/);
    expect(buttons[1]).toHaveTextContent(/^Procesar amortización$/);
    expect(buttons[1]).toHaveClass("primary");
  });

  it("permite rotular la salida (p. ej. «Volver») sin pedir escribir una palabra", async () => {
    const onCancel = vi.fn();
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Cerrar sin amortizar"
        confirmLabel="Confirmar cierre"
        cancelLabel="Volver"
        onConfirm={onConfirm}
        onCancel={onCancel}
      >
        <p>Detalle</p>
      </ConfirmDialog>,
    );
    expect(screen.queryByRole("textbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Volver" }));
    expect(onCancel).toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Confirmar cierre" }));
    expect(onConfirm).toHaveBeenCalled();
  });
});

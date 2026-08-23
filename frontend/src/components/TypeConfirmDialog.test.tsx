import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TypeConfirmDialog } from "./TypeConfirmDialog";

describe("TypeConfirmDialog", () => {
  it("exige escribir CANCELAR antes de confirmar", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <TypeConfirmDialog
        title="Cancelar lote"
        confirmLabel="Confirmar cancelación"
        onConfirm={onConfirm}
        onCancel={() => undefined}
      >
        <p>Se descartará el lote.</p>
      </TypeConfirmDialog>,
    );

    const confirmBtn = screen.getByRole("button", { name: /Confirmar cancelación/i });
    expect(confirmBtn).toBeDisabled();

    await user.type(screen.getByPlaceholderText("CANCELAR"), "cancelar");
    expect(confirmBtn).toBeDisabled();

    await user.clear(screen.getByPlaceholderText("CANCELAR"));
    await user.type(screen.getByPlaceholderText("CANCELAR"), "CANCELAR");
    expect(confirmBtn).toBeEnabled();

    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("no pide motivo: basta escribir CANCELAR", async () => {
    const user = userEvent.setup();
    const onConfirm = vi.fn();
    render(
      <TypeConfirmDialog
        title="Cerrar sin amortizar"
        confirmLabel="Confirmar cierre"
        onConfirm={onConfirm}
        onCancel={() => undefined}
      >
        <p>Se cierra sin amortizar.</p>
      </TypeConfirmDialog>,
    );

    expect(screen.queryByLabelText(/Motivo/i)).not.toBeInTheDocument();
    const confirmBtn = screen.getByRole("button", { name: /Confirmar cierre/i });
    await user.type(screen.getByPlaceholderText("CANCELAR"), "CANCELAR");
    expect(confirmBtn).toBeEnabled();
    await user.click(confirmBtn);
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("usa variante danger y Volver a la izquierda", async () => {
    const user = userEvent.setup();
    render(
      <TypeConfirmDialog
        title="Cancelar lote"
        confirmLabel="Cancelar proceso"
        onConfirm={() => undefined}
        onCancel={() => undefined}
      >
        <p>Se descartará el lote.</p>
      </TypeConfirmDialog>,
    );
    await user.type(screen.getByPlaceholderText("CANCELAR"), "CANCELAR");
    const buttons = screen.getAllByRole("button");
    expect(buttons[0]).toHaveTextContent(/^Volver$/);
    expect(buttons[1]).toHaveTextContent(/^Cancelar proceso$/);
    expect(buttons[1]).toHaveClass("danger");
  });
});

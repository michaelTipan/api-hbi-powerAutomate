import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { Modal } from "./Modal";

function TestModal({ onClose }: { onClose: () => void }) {
  return (
    <Modal titleId="t" title="Título de prueba" onClose={onClose}>
      <button type="button">Primero</button>
      <button type="button">Segundo</button>
    </Modal>
  );
}

describe("Modal", () => {
  it("expone role=dialog y aria-modal=true", () => {
    render(<TestModal onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog", { name: "Título de prueba" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("enfoca el primer elemento interactivo al abrir", () => {
    render(<TestModal onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Primero" })).toHaveFocus();
  });

  it("cierra al presionar Escape", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<TestModal onClose={onClose} />);
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("no cierra con Escape cuando closeDisabled=true", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Modal titleId="t2" title="Bloqueado" onClose={onClose} closeDisabled>
        <button type="button">Ok</button>
      </Modal>,
    );
    await user.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("atrapa el foco: Tab desde el último botón vuelve al primero", async () => {
    const user = userEvent.setup();
    render(<TestModal onClose={vi.fn()} />);
    const first = screen.getByRole("button", { name: "Primero" });
    const last = screen.getByRole("button", { name: "Segundo" });
    last.focus();
    await user.tab();
    expect(first).toHaveFocus();
  });

  it("no tiene violaciones de accesibilidad detectables por axe", async () => {
    const { container } = render(<TestModal onClose={vi.fn()} />);
    const results = await axe(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations).toEqual([]);
  });
});

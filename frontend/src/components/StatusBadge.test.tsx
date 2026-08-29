import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("aplica clase status-pill según tono semántico", () => {
    const { container } = render(
      <StatusBadge status="COMPLETADO">Listo</StatusBadge>,
    );
    const pill = container.querySelector(".status-pill.ok");
    expect(pill).toBeTruthy();
    expect(screen.getByText("Listo")).toBeInTheDocument();
  });

  it("renderiza sin tono para estado neutral", () => {
    const { container } = render(<StatusBadge status="">—</StatusBadge>);
    const pill = container.querySelector(".status-pill");
    expect(pill).toBeTruthy();
    expect(pill?.className).not.toMatch(/\bok\b|\binfo\b|\bwarn\b|\bdanger\b/);
  });
});

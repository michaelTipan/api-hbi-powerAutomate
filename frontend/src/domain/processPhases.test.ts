import { describe, expect, it } from "vitest";
import type { UiLink, UiStepState } from "../types/contract";
import {
  documentsForPhase,
  documentSectionsForUnlockedPhases,
  HIDDEN_DOCUMENT_RELS,
  isOperatorVisibleLink,
  OPERATOR_PHASES,
  operatorDocumentLabel,
  resolveOperatorPhases,
} from "./processPhases";

function step(name: UiStepState["name"], status: UiStepState["status"]): UiStepState {
  return { name, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
}

function link(rel: string, label = rel): UiLink {
  return { rel, label, path: `${rel}.xlsx`, web_url: `https://example.com/${rel}`, open_mode: "sharepoint" };
}

describe("resolveOperatorPhases", () => {
  it("marca Revisión como actual cuando el Excel está pendiente", () => {
    const { phases, currentId } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    expect(currentId).toBe("review");
    expect(phases.find((p) => p.def.id === "review")?.visual).toBe("current");
    expect(phases.find((p) => p.def.id === "notify")?.visual).toBe("upcoming");
  });

  it("avanza a Envío tras cerrar la revisión", () => {
    const { currentId, phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    expect(currentId).toBe("notify");
    expect(phases.find((p) => p.def.id === "finalize")?.visual).toBe("completed");
    expect(phases.find((p) => p.def.id === "finalize")?.unlocked).toBe(true);
  });

  it("trata Amortización como actual cuando Merge está listo", () => {
    const { currentId } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "completed"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    expect(currentId).toBe("amortization");
  });
});

describe("documentos por fase", () => {
  it("oculta control y registro de ejecución", () => {
    expect(HIDDEN_DOCUMENT_RELS.has("control")).toBe(true);
    expect(isOperatorVisibleLink(link("control"))).toBe(false);
    expect(isOperatorVisibleLink(link("review_excel"))).toBe(true);
  });

  it("nunca usa la palabra secretaría en etiquetas", () => {
    expect(operatorDocumentLabel(link("secretary_file", "Abrir soporte secretaría"))).toBe(
      "Abrir asientos pendientes",
    );
  });

  it("solo expone secciones desbloqueadas con enlaces", () => {
    const { phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    const links = [
      link("review_excel"),
      link("historical"),
      link("secretary_file"),
      link("control"),
      link("email_pdf"),
    ];
    const sections = documentSectionsForUnlockedPhases(links, phases);
    expect(sections.every((s) => s.links.every((l) => l.rel !== "control"))).toBe(true);
    expect(sections.map((s) => s.phase.id)).toEqual(
      expect.arrayContaining(["review", "finalize", "notify"]),
    );
    expect(sections.map((s) => s.phase.id)).not.toContain("merge");
    const reviewDocs = documentsForPhase(links, OPERATOR_PHASES[0]!);
    expect(reviewDocs.map((l) => l.rel)).toEqual(["review_excel"]);
  });
});

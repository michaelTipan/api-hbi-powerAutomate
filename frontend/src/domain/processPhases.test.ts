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
  shouldShowRefreshDocuments,
  shouldShowStatusRefresh,
} from "./processPhases";

function step(name: UiStepState["name"], status: UiStepState["status"]): UiStepState {
  return { name, status, updated_at: null, summary: null, can_retry: false, retry_action: null };
}

function link(rel: string, label = rel): UiLink {
  return { rel, label, path: `${rel}.xlsx`, web_url: `https://example.com/${rel}`, open_mode: "sharepoint" };
}

describe("resolveOperatorPhases", () => {
  it("tras Generate completa, Finalizar revisión es la fase actual", () => {
    const { phases, currentId } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    expect(currentId).toBe("finalize");
    expect(phases.find((p) => p.def.id === "review")?.visual).toBe("completed");
    expect(phases.find((p) => p.def.id === "finalize")?.visual).toBe("current");
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

  it("nunca muestra carpetas ASIENTOS en documentos de fase", () => {
    expect(isOperatorVisibleLink(link("asientos"))).toBe(false);
    expect(isOperatorVisibleLink(link("asientos_folder"))).toBe(false);
    expect(isOperatorVisibleLink(link("asientos_folder:0"))).toBe(false);
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
    // notify está desbloqueada (actual) y aporta email_pdf; merge aún no.
    expect(sections.map((s) => s.phase.id)).toEqual(["review", "finalize", "notify"]);
    expect(sections.map((s) => s.phase.id)).not.toContain("merge");
    const reviewDocs = documentsForPhase(links, OPERATOR_PHASES[0]!);
    expect(reviewDocs.map((l) => l.rel)).toEqual(["review_excel"]);
  });

  it("oculta Actualizar documentos en revisión y lo muestra en Merge parcial", () => {
    const reviewSteps = [
      step("generate", "completed"),
      step("review", "in_progress"),
      step("finalize", "not_started"),
      step("notify", "not_started"),
      step("merge", "not_started"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ];
    expect(
      shouldShowRefreshDocuments({
        currentPhaseId: "review",
        operationalStatus: "EN_REVISION",
        nextActions: [{ code: "refresh_documents" }],
        steps: reviewSteps,
        links: [link("review_excel")],
      }),
    ).toBe(false);

    const mergeSteps = [
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "partial"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ];
    expect(
      shouldShowRefreshDocuments({
        currentPhaseId: "merge",
        operationalStatus: "ESPERANDO_SOPORTES",
        controlEstadoProceso: "PENDIENTE_ASIENTOS",
        nextActions: [{ code: "refresh_documents" }],
        steps: mergeSteps,
        links: [link("email_pdf"), { ...link("merge_pdf"), web_url: null }],
      }),
    ).toBe(true);

    expect(
      shouldShowRefreshDocuments({
        currentPhaseId: "amortization",
        operationalStatus: "LISTO_PARA_APLICAR",
        nextActions: [],
        steps: [
          ...mergeSteps.slice(0, 5).map((s) =>
            s.name === "merge" ? step("merge", "completed") : s,
          ),
          step("dry_run", "completed"),
          step("apply", "not_started"),
        ],
        links: [link("merge_pdf")],
      }),
    ).toBe(false);

    expect(
      shouldShowRefreshDocuments({
        currentPhaseId: "merge",
        operationalStatus: "COMPLETADO",
        nextActions: [{ code: "refresh_documents" }],
        steps: mergeSteps,
        links: [{ ...link("merge_pdf"), web_url: null }],
      }),
    ).toBe(false);
  });

  it("nunca muestra ambos botones de recarga a la vez", () => {
    const mergeSteps = [
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "blocked"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ];
    const cases = [
      {
        currentPhaseId: "review" as const,
        operationalStatus: "EN_REVISION",
        nextActions: [] as { code: string }[],
        steps: [
          step("generate", "completed"),
          step("review", "in_progress"),
          step("finalize", "not_started"),
          step("notify", "not_started"),
          step("merge", "not_started"),
          step("dry_run", "not_started"),
          step("apply", "not_started"),
        ],
        links: [link("review_excel")],
      },
      {
        currentPhaseId: "merge" as const,
        operationalStatus: "ESPERANDO_SOPORTES",
        nextActions: [{ code: "refresh_documents" }],
        steps: mergeSteps,
        links: [{ ...link("merge_pdf"), web_url: null }],
      },
      {
        currentPhaseId: "amortization" as const,
        operationalStatus: "COMPLETADO",
        nextActions: [],
        steps: [
          ...mergeSteps.map((s) => (s.name === "merge" ? step("merge", "completed") : s)),
          step("dry_run", "completed"),
          step("apply", "completed"),
        ],
        links: [link("merge_pdf")],
      },
      {
        currentPhaseId: "amortization" as const,
        operationalStatus: "COMPLETADO",
        nextActions: [],
        steps: [
          ...mergeSteps.map((s) => (s.name === "merge" ? step("merge", "completed") : s)),
          step("dry_run", "completed"),
          step("apply", "completed"),
        ],
        links: [{ ...link("merge_pdf"), web_url: null }],
      },
    ];
    for (const c of cases) {
      const docs = shouldShowRefreshDocuments(c);
      const status = shouldShowStatusRefresh({
        operationalStatus: c.operationalStatus,
        showRefreshDocuments: docs,
        links: c.links,
      });
      expect(docs && status).toBe(false);
    }
  });

  it("en COMPLETADO no muestra recarga salvo enlace no disponible (consulta)", () => {
    const completedSteps = [
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "completed"),
      step("dry_run", "completed"),
      step("apply", "completed"),
    ];
    const docsOk = shouldShowRefreshDocuments({
      currentPhaseId: "amortization",
      operationalStatus: "COMPLETADO",
      nextActions: [],
      steps: completedSteps,
      links: [link("merge_pdf")],
    });
    expect(docsOk).toBe(false);
    expect(
      shouldShowStatusRefresh({
        operationalStatus: "COMPLETADO",
        showRefreshDocuments: docsOk,
        links: [link("merge_pdf")],
      }),
    ).toBe(false);

    const docsUnavailable = shouldShowRefreshDocuments({
      currentPhaseId: "amortization",
      operationalStatus: "COMPLETADO",
      nextActions: [{ code: "refresh_documents" }],
      steps: completedSteps,
      links: [{ ...link("merge_pdf"), web_url: null }],
    });
    expect(docsUnavailable).toBe(false);
    expect(
      shouldShowStatusRefresh({
        operationalStatus: "COMPLETADO",
        showRefreshDocuments: docsUnavailable,
        links: [{ ...link("merge_pdf"), web_url: null }],
      }),
    ).toBe(true);
  });

  it("no duplica el mismo documento en varias fases", () => {
    const { phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "completed"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    const links = [
      link("review_excel"),
      link("historical"),
      link("secretary_file"),
      link("email_pdf"),
      link("merge_pdf"),
    ];
    const sections = documentSectionsForUnlockedPhases(links, phases);
    const allRels = sections.flatMap((s) => s.links.map((l) => l.rel));
    expect(allRels).toEqual(["review_excel", "historical", "secretary_file", "email_pdf", "merge_pdf"]);
    expect(new Set(allRels).size).toBe(allRels.length);
    expect(sections.find((s) => s.phase.id === "amortization")).toBeUndefined();
    expect(OPERATOR_PHASES.map((p) => p.shortLabel)).toEqual([
      "Generar archivo",
      "Finalizar revisión",
      "Enviar correo",
      "Generar PDF consolidado",
      "Procesar amortización",
    ]);
  });

  it("incluye todos los PDFs consolidados (merge_pdf:N) en Documentos por fase", () => {
    const { phases } = resolveOperatorPhases([
      step("generate", "completed"),
      step("review", "completed"),
      step("finalize", "completed"),
      step("notify", "completed"),
      step("merge", "completed"),
      step("dry_run", "not_started"),
      step("apply", "not_started"),
    ]);
    const links = [
      {
        ...link("merge_pdf:0"),
        label: "Abrir PDF consolidado · Crédito 265",
        web_url: "https://example.com/a.pdf",
      },
      {
        ...link("merge_pdf:1"),
        label: "Abrir PDF consolidado · Crédito 310",
        web_url: "https://example.com/b.pdf",
      },
    ];
    const mergePhase = phases.find((p) => p.def.id === "merge")!;
    const docs = documentsForPhase(links, mergePhase.def);
    expect(docs.map((d) => d.rel)).toEqual(["merge_pdf:0", "merge_pdf:1"]);
    expect(operatorDocumentLabel(docs[0]!)).toBe("Abrir PDF consolidado · Crédito 265");
    expect(operatorDocumentLabel(docs[1]!)).toBe("Abrir PDF consolidado · Crédito 310");
  });
});

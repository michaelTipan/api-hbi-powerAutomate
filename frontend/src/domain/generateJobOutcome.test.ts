import { describe, expect, it } from "vitest";
import {
  isReviewErroresIssue,
  resolveGenerateReviewErrorCount,
  reviewErrorCountFromDetail,
  reviewErrorCountFromJob,
} from "./generateJobOutcome";

describe("reviewErrorCountFromJob", () => {
  it("lee errores en la raíz de result_summary", () => {
    expect(reviewErrorCountFromJob({ result_summary: { errores: 3 } })).toBe(3);
  });

  it("lee errores anidados en summary (payload Generate)", () => {
    expect(
      reviewErrorCountFromJob({
        result_summary: { summary: { errores: 2, pagos_banco: 10 } },
      }),
    ).toBe(2);
  });

  it("devuelve 0 si el lote salió limpio", () => {
    expect(reviewErrorCountFromJob({ result_summary: { errores: 0 } })).toBe(0);
  });

  it("devuelve null si el job no trae conteo", () => {
    expect(reviewErrorCountFromJob({ result_summary: { validation_file_url: "x" } })).toBe(
      null,
    );
    expect(reviewErrorCountFromJob({ result_summary: null })).toBe(null);
  });
});

describe("isReviewErroresIssue / resolveGenerateReviewErrorCount", () => {
  it("reconoce hoja Errores por id o sheet", () => {
    expect(isReviewErroresIssue({ issue_id: "review-errores-1" })).toBe(true);
    expect(
      isReviewErroresIssue({ issue_id: "other", location: { sheet: "Errores" } }),
    ).toBe(true);
    expect(isReviewErroresIssue({ issue_id: "review-file-missing" })).toBe(false);
  });

  it("cuenta issues del detalle si el job no trae errores", () => {
    const detail = {
      operational_issues: [
        { issue_id: "review-errores-1" },
        { issue_id: "review-file-missing" },
      ],
    };
    expect(reviewErrorCountFromDetail(detail)).toBe(1);
    expect(resolveGenerateReviewErrorCount({ result_summary: null }, detail)).toBe(1);
  });

  it("el conteo del job gana sobre el detalle stale", () => {
    expect(
      resolveGenerateReviewErrorCount(
        { result_summary: { errores: 0 } },
        { operational_issues: [{ issue_id: "review-errores-1" }] },
      ),
    ).toBe(0);
  });
});

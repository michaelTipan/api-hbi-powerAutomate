import { describe, expect, it } from "vitest";
import {
  CORRECTION_INLINE_ISSUE_MAX,
  countOpenableCorrectionLinks,
  primaryIssueLinks,
  shouldUseCorrectionTargetsDrawer,
} from "./correctionTargets";
import type { UiLink, UiOperationalIssue } from "../types/contract";

function link(rel: string, url: string | null): UiLink {
  return {
    rel,
    label: rel,
    path: null,
    web_url: url,
    open_mode: "sharepoint",
  };
}

function issue(
  id: string,
  links: UiLink[],
): UiOperationalIssue {
  return {
    issue_id: id,
    stage: "generate",
    category: "correction_required",
    severity: "business",
    recoverable: true,
    title: `Caso ${id}`,
    user_message: "Mensaje",
    location: null,
    value_found: null,
    expected_values: [],
    next_action: "Corregir",
    retry: null,
    links,
    technical_reference: null,
  };
}

describe("correctionTargets", () => {
  it("primaryIssueLinks limita a 2 con web_url", () => {
    const i = issue("a", [
      link("error_extract", "https://sp/a"),
      link("error_folder", "https://sp/b"),
      link("review_excel", "https://sp/c"),
      link("bank_input", null),
    ]);
    const primary = primaryIssueLinks(i);
    expect(primary).toHaveLength(2);
    expect(primary.map((l) => l.rel)).toEqual(["error_extract", "error_folder"]);
  });

  it("shouldUseCorrectionTargetsDrawer con muchos issues", () => {
    const many = Array.from({ length: CORRECTION_INLINE_ISSUE_MAX + 1 }, (_, n) =>
      issue(`i-${n}`, [link("review_excel", "https://sp/x")]),
    );
    expect(shouldUseCorrectionTargetsDrawer(many)).toBe(true);
    expect(shouldUseCorrectionTargetsDrawer(many.slice(0, 2))).toBe(false);
  });

  it("shouldUseCorrectionTargetsDrawer con muchos links", () => {
    const fewIssuesManyLinks = [
      issue("a", [
        link("a1", "https://sp/1"),
        link("a2", "https://sp/2"),
        link("a3", "https://sp/3"),
        link("a4", "https://sp/4"),
      ]),
      issue("b", [
        link("b1", "https://sp/5"),
        link("b2", "https://sp/6"),
        link("b3", "https://sp/7"),
        link("b4", "https://sp/8"),
      ]),
      issue("c", [
        link("c1", "https://sp/9"),
        link("c2", "https://sp/10"),
        link("c3", "https://sp/11"),
      ]),
    ];
    expect(countOpenableCorrectionLinks(fewIssuesManyLinks)).toBe(11);
    expect(shouldUseCorrectionTargetsDrawer(fewIssuesManyLinks)).toBe(true);
  });
});

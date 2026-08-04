import { useEffect, useId, useMemo, useState } from "react";
import type { UiOperationalIssue } from "../types/contract";
import { correctionTargetEntryLabel } from "../domain/correctionTargets";
import { Modal } from "./Modal";
import { OperationalIssuePanel } from "./OperationalIssuePanel";

const CATEGORY_LABELS: Record<string, string> = {
  correction_required: "Corrección requerida",
  temporary_failure: "Fallo temporal",
  system_failure: "Fallo del sistema",
  warning: "Advertencia",
  partial_result: "Resultado parcial",
};

/** Etiquetas operativas para códigos técnicos de amortización/asiento (sin jerga). */
const TECH_CODE_GROUP_LABELS: Record<string, string> = {
  PDF_TEXT_NOT_EXTRACTABLE: "PDF sin texto legible",
  ACCOUNTING_PARSE_FAILED: "Formato de asiento no reconocido",
  MISSING_BANK_VALUE_BUT_HAS_ACCOUNTING_LINES: "Falta línea del banco",
  ASIENTO_PATH_MISSING: "Falta PDF del asiento",
  ASIENTO_DOWNLOAD_FAILED: "No se pudo descargar el asiento",
  TABLE_PATH_NOT_FOUND: "Tabla de amortización no encontrada",
  TABLE_DOWNLOAD_FAILED: "No se pudo descargar la tabla",
  AMORTIZATION_SHEET_NOT_FOUND: "Estructura de tabla incompleta",
  ABONO_ASIENTOS_NO_CUADRAN: "Abono sin cuadre",
  ABONO_ASIENTO_FALTANTE: "Falta asiento del abono",
  MERGE_GROUP_PENDING_INPUTS: "Consolidación incompleta",
  MERGE_INCOMPLETE_NOT_APPLICABLE: "Consolidación incompleta",
};

/** Código técnico (codigo_tecnico) o categoría para agrupar. */
export function issueGroupKey(issue: UiOperationalIssue): string {
  const ref = (issue.technical_reference || "").trim();
  if (ref) {
    const codeMatch = /(?:^|\|)code:([^|]+)/i.exec(ref);
    if (codeMatch?.[1]?.trim()) return codeMatch[1].trim();
    if (!ref.includes("|") && !ref.includes(":")) return ref;
  }
  return issue.category || "otros";
}

function humanizeCode(code: string): string {
  return code
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function issueGroupLabel(key: string): string {
  if (CATEGORY_LABELS[key]) return CATEGORY_LABELS[key];
  const trimmed = key.trim();
  const upper = trimmed.toUpperCase();
  if (TECH_CODE_GROUP_LABELS[upper]) return TECH_CODE_GROUP_LABELS[upper];
  if (TECH_CODE_GROUP_LABELS[trimmed]) return TECH_CODE_GROUP_LABELS[trimmed];
  // Códigos amort ALL_CAPS (p. ej. ACCOUNTING_PARSE_FAILED): no Title-Case inglés.
  if (/^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/.test(trimmed)) {
    return "Problema de amortización";
  }
  return humanizeCode(trimmed);
}

type IssueGroup = {
  key: string;
  label: string;
  issues: UiOperationalIssue[];
};

function buildGroups(issues: readonly UiOperationalIssue[]): IssueGroup[] {
  const map = new Map<string, UiOperationalIssue[]>();
  for (const issue of issues) {
    const key = issueGroupKey(issue);
    const list = map.get(key);
    if (list) list.push(issue);
    else map.set(key, [issue]);
  }
  return [...map.entries()].map(([key, groupIssues]) => ({
    key,
    label: issueGroupLabel(key),
    issues: groupIssues,
  }));
}

/**
 * Modal con el detalle completo de problemas operativos (hoja Errores u otros).
 * Evita saturar ProcessDetailPage: la página solo muestra un banner compacto.
 */
export function OperationalIssuesModal({
  open,
  title = "Problemas operativos",
  issues,
  onClose,
  onRetryFor,
  retryBusy = false,
}: {
  open: boolean;
  title?: string;
  issues: readonly UiOperationalIssue[];
  onClose: () => void;
  onRetryFor?: (action: string | null | undefined) => (() => void) | undefined;
  retryBusy?: boolean;
}) {
  const titleId = useId();
  const searchId = useId();
  const [query, setQuery] = useState("");
  const [activeGroupKey, setActiveGroupKey] = useState<string | "all">("all");

  useEffect(() => {
    if (!open) {
      setQuery("");
      setActiveGroupKey("all");
    }
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...issues];
    return issues.filter((issue) => {
      const label = correctionTargetEntryLabel(issue);
      const linksTxt = (issue.links ?? [])
        .map((l) => `${l.label} ${l.rel}`)
        .join(" ");
      const tech = issue.technical_reference ?? "";
      const hay =
        `${label} ${issue.user_message} ${issue.next_action ?? ""} ${linksTxt} ${tech}`.toLowerCase();
      return hay.includes(q);
    });
  }, [issues, query]);

  const groups = useMemo(() => buildGroups(filtered), [filtered]);
  const distinctCodes = useMemo(() => {
    const keys = new Set(issues.map(issueGroupKey));
    return keys.size;
  }, [issues]);

  const showSearch = issues.length >= 8;
  const useChipNav = issues.length > 5 && distinctCodes >= 2;
  const showGroupHeadings =
    !useChipNav && filtered.length > 0 && groups.length >= 2;

  const visibleIssues = useMemo(() => {
    if (!useChipNav || activeGroupKey === "all") return filtered;
    return filtered.filter((i) => issueGroupKey(i) === activeGroupKey);
  }, [useChipNav, activeGroupKey, filtered]);

  const visibleGroups = useMemo(() => {
    if (useChipNav) {
      if (activeGroupKey === "all") return groups;
      return groups.filter((g) => g.key === activeGroupKey);
    }
    if (showGroupHeadings) return groups;
    return [{ key: "all", label: "", issues: filtered }];
  }, [useChipNav, activeGroupKey, groups, showGroupHeadings, filtered]);

  if (!open) return null;

  return (
    <Modal
      titleId={titleId}
      title={`${title} (${issues.length})`}
      onClose={onClose}
    >
      <div className="operational-issues-modal">
        <p className="meta" style={{ marginTop: 0 }}>
          Revise cada caso, abra los enlaces en SharePoint y regenere o verifique
          según corresponda.
        </p>
        {showSearch ? (
          <div className="link-catalog-search">
            <label className="sr-only" htmlFor={searchId}>
              Buscar problemas operativos
            </label>
            <input
              id={searchId}
              type="search"
              className="link-catalog-search-input"
              placeholder="Buscar por crédito, cliente o mensaje…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        ) : null}
        {useChipNav ? (
          <div
            className="operational-issues-group-chips"
            role="tablist"
            aria-label="Filtrar por tipo de problema"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeGroupKey === "all"}
              className={`btn secondary btn-compact${activeGroupKey === "all" ? " is-selected" : ""}`}
              onClick={() => setActiveGroupKey("all")}
            >
              Todos ({filtered.length})
            </button>
            {groups.map((g) => (
              <button
                key={g.key}
                type="button"
                role="tab"
                aria-selected={activeGroupKey === g.key}
                className={`btn secondary btn-compact${activeGroupKey === g.key ? " is-selected" : ""}`}
                onClick={() => setActiveGroupKey(g.key)}
              >
                {g.label} ({g.issues.length})
              </button>
            ))}
          </div>
        ) : null}
        {visibleIssues.length === 0 ? (
          <p className="muted">No hay coincidencias.</p>
        ) : (
          <div className="operational-issues-modal-list">
            {visibleGroups.map((group) => (
              <div key={group.key} className="operational-issues-group">
                {group.label ? (
                  <h3 className="operational-issues-group-title">
                    {group.label}
                    <span className="muted"> ({group.issues.length})</span>
                  </h3>
                ) : null}
                {group.issues.map((issue) => (
                  <OperationalIssuePanel
                    key={issue.issue_id}
                    issue={issue}
                    onRetry={onRetryFor?.(issue.retry?.action)}
                    retryBusy={retryBusy}
                    maxPrimaryLinks={Number.POSITIVE_INFINITY}
                  />
                ))}
              </div>
            ))}
          </div>
        )}
        <div className="modal-actions">
          <button type="button" className="btn secondary" onClick={onClose}>
            Cerrar
          </button>
        </div>
      </div>
    </Modal>
  );
}

import { useEffect, useId, useMemo, useState } from "react";
import type { UiOperationalIssue } from "../types/contract";
import { correctionTargetEntryLabel } from "../domain/correctionTargets";
import {
  partitionOperationalIssuesForModal,
  sharedFinalizeRetryAction,
  sharedReviewExcelLink,
  type FinalizeRowIssueGroup,
} from "../domain/finalizeDistributionIssues";
import { actionExplanations, actionLabels } from "../copy/labels";
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

/** Código técnico o categoría para agrupar (hoja Errores / amortización). */
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
  // Códigos amort ALL_CAPS: no Title-Case en inglés.
  if (/^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/.test(trimmed)) {
    return "Problema de amortización";
  }
  // Códigos snake_case de Finalize/Distribución: etiqueta genérica en español
  // (no «Missing Mora A Aplicar»).
  if (/^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/.test(trimmed)) {
    return "Corrección en la revisión";
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

function rowGroupMatchesQuery(group: FinalizeRowIssueGroup, q: string): boolean {
  const hay = [
    group.title,
    group.credit,
    group.paymentId,
    group.clientName,
    ...group.messages,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return hay.includes(q);
}

function FinalizeRowGroupCard({ group }: { group: FinalizeRowIssueGroup }) {
  const metaParts = [
    group.credit ? `Crédito ${group.credit}` : null,
    group.clientName || null,
    group.paymentId ? `ID pago ${group.paymentId}` : null,
  ].filter(Boolean);

  return (
    <div className="error-box" role="alert" data-row-group={group.key}>
      <strong>{group.title}</strong>
      {metaParts.length > 0 ? (
        <p className="meta" style={{ margin: "0.35rem 0" }}>
          {metaParts.join(" · ")}
        </p>
      ) : null}
      {group.messages.length > 0 ? (
        <ul className="operational-issues-row-messages">
          {group.messages.map((msg) => (
            <li key={msg}>{msg}</li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: "0.35rem 0" }}>Hay correcciones pendientes en esta fila.</p>
      )}
    </div>
  );
}

/**
 * Modal con el detalle completo de problemas operativos.
 * Distribución/Finalize: una tarjeta por fila + CTAs únicos al Excel.
 * Hoja Errores / amortización: paneles por issue (sin cambiar).
 */
export function OperationalIssuesModal({
  open,
  title = "Problemas operativos",
  issues,
  onClose,
  onRetryFor,
  retryBusy = false,
  formatRecovery = false,
  onGoReconsolidate,
}: {
  open: boolean;
  title?: string;
  issues: readonly UiOperationalIssue[];
  onClose: () => void;
  onRetryFor?: (action: string | null | undefined) => (() => void) | undefined;
  retryBusy?: boolean;
  /** Modo recuperación post-formato de asiento (CTA reconsolidar). */
  formatRecovery?: boolean;
  onGoReconsolidate?: () => void;
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

  const { rowGroups, otherIssues } = useMemo(
    () => partitionOperationalIssuesForModal(issues),
    [issues],
  );
  const rowModeOnly = rowGroups.length > 0 && otherIssues.length === 0;

  const filteredRowGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rowGroups;
    return rowGroups.filter((g) => rowGroupMatchesQuery(g, q));
  }, [rowGroups, query]);

  const filteredOther = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [...otherIssues];
    return otherIssues.filter((issue) => {
      const label = correctionTargetEntryLabel(issue);
      const linksTxt = (issue.links ?? [])
        .map((l) => `${l.label} ${l.rel}`)
        .join(" ");
      const tech = issue.technical_reference ?? "";
      const hay =
        `${label} ${issue.user_message} ${issue.next_action ?? ""} ${linksTxt} ${tech}`.toLowerCase();
      return hay.includes(q);
    });
  }, [otherIssues, query]);

  const groups = useMemo(() => buildGroups(filteredOther), [filteredOther]);
  const distinctCodes = useMemo(() => {
    const keys = new Set(otherIssues.map(issueGroupKey));
    return keys.size;
  }, [otherIssues]);

  const displayCount = rowModeOnly
    ? rowGroups.length
    : rowGroups.length > 0
      ? rowGroups.length + otherIssues.length
      : issues.length;

  const showSearch = issues.length >= 8 || rowGroups.length >= 8;
  // Chips por tipo: solo para hoja Errores / amort (no Distribución por fila).
  const useChipNav =
    !rowModeOnly &&
    otherIssues.length > 5 &&
    distinctCodes >= 2 &&
    rowGroups.length === 0;
  const showGroupHeadings =
    !useChipNav && filteredOther.length > 0 && groups.length >= 2;

  const visibleOtherIssues = useMemo(() => {
    if (!useChipNav || activeGroupKey === "all") return filteredOther;
    return filteredOther.filter((i) => issueGroupKey(i) === activeGroupKey);
  }, [useChipNav, activeGroupKey, filteredOther]);

  const visibleGroups = useMemo(() => {
    if (useChipNav) {
      if (activeGroupKey === "all") return groups;
      return groups.filter((g) => g.key === activeGroupKey);
    }
    if (showGroupHeadings) return groups;
    return [{ key: "all", label: "", issues: filteredOther }];
  }, [useChipNav, activeGroupKey, groups, showGroupHeadings, filteredOther]);

  const sharedLink = useMemo(
    () => sharedReviewExcelLink(rowGroups.flatMap((g) => g.issues)),
    [rowGroups],
  );
  const sharedRetry = useMemo(
    () => sharedFinalizeRetryAction(rowGroups.flatMap((g) => g.issues)),
    [rowGroups],
  );
  const sharedRetryHandler =
    sharedRetry && onRetryFor ? onRetryFor(sharedRetry.action) : undefined;

  if (!open) return null;

  const showRecoveryCta = Boolean(formatRecovery && onGoReconsolidate);
  const hasVisibleContent =
    filteredRowGroups.length > 0 || visibleOtherIssues.length > 0;

  return (
    <Modal
      titleId={titleId}
      title={`${title} (${displayCount})`}
      onClose={onClose}
    >
      <div className="operational-issues-modal">
        <p className="meta" style={{ marginTop: 0 }}>
          {formatRecovery
            ? actionExplanations.amortization_format_recovery_intro
            : rowModeOnly
              ? "Revise cada fila, corrija el Excel de revisión, guarde y verifique de nuevo."
              : "Revise cada caso, abra los enlaces en SharePoint y regenere o verifique según corresponda."}
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
              Todos ({filteredOther.length})
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
        {!hasVisibleContent ? (
          <p className="muted">No hay coincidencias.</p>
        ) : (
          <div className="operational-issues-modal-list">
            {filteredRowGroups.length > 0 ? (
              <div className="operational-issues-group">
                {!rowModeOnly ? (
                  <h3 className="operational-issues-group-title">
                    Correcciones en el Excel de revisión
                    <span className="muted"> ({filteredRowGroups.length})</span>
                  </h3>
                ) : null}
                {filteredRowGroups.map((group) => (
                  <FinalizeRowGroupCard key={group.key} group={group} />
                ))}
              </div>
            ) : null}
            {visibleGroups.map((group) =>
              group.issues.length === 0 ? null : (
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
              ),
            )}
          </div>
        )}
        {rowGroups.length > 0 && (sharedLink?.web_url || sharedRetryHandler) ? (
          <div className="actions operational-issues-shared-actions">
            {sharedLink?.web_url ? (
              <a
                className="btn secondary"
                href={sharedLink.web_url}
                target="_blank"
                rel="noreferrer"
              >
                {sharedLink.label || actionLabels.open_review_excel}
              </a>
            ) : null}
            {sharedRetryHandler ? (
              <button
                type="button"
                className="btn primary"
                onClick={sharedRetryHandler}
                disabled={retryBusy}
              >
                {sharedRetry?.label || "Verificar nuevamente"}
              </button>
            ) : null}
          </div>
        ) : null}
        <div className="modal-actions">
          <button type="button" className="btn secondary" onClick={onClose}>
            Cerrar
          </button>
          {showRecoveryCta ? (
            <button
              type="button"
              className="btn primary"
              onClick={onGoReconsolidate}
            >
              {actionLabels.go_reconsolidate}
            </button>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

import { useState, type ReactNode } from "react";
import type {
  ExclusionReasonCode,
  UiAmortizationDecisions,
  UiOperationalIssue,
} from "../types/contract";
import {
  EXCLUSION_NOTE_MAX,
  confirmationForIssue,
  creditToken,
  excludeCreditButtonLabel,
  excludeSubmitLabel,
  exclusionForIssue,
  exclusionFormTitle,
  formatCop,
  groupExclusionWarning,
} from "../domain/amortizationDecisions";
import { ExclusionReasonForm } from "./ExclusionReasonForm";
import { LoadingButton } from "./LoadingButton";

/** Cada handler resuelve null si se guardó, o el mensaje de error para el operador. */
export type AmortizationDecisionHandlers = {
  onExclude: (credit: string, motivo: ExclusionReasonCode, nota: string) => Promise<string | null>;
  onUndoExclude: (credit: string) => Promise<string | null>;
  onConfirm: (conciliationKey: string, nota: string) => Promise<string | null>;
  onUndoConfirm: (conciliationKey: string) => Promise<string | null>;
};

/**
 * Salidas del operador para un problema de amortización: excluir el crédito o
 * continuar con los asientos. Excluido/confirmado → recuadro neutro con «Deshacer».
 */
export function AmortizationIssueDecision({
  issue,
  panel,
  decisions,
  handlers,
  disabled = false,
}: {
  issue: UiOperationalIssue;
  /** Tarjeta del problema; como función recibe el pie con las acciones. */
  panel: ReactNode | ((footer?: ReactNode) => ReactNode);
  decisions: UiAmortizationDecisions | null | undefined;
  handlers: AmortizationDecisionHandlers;
  disabled?: boolean;
}) {
  const [mode, setMode] = useState<"idle" | "excluding" | "note">("idle");
  const [confirmNote, setConfirmNote] = useState("");
  const [busy, setBusy] = useState<null | "exclude" | "undo" | "confirm">(null);
  const [error, setError] = useState<string | null>(null);

  // Panel con pie: las acciones quedan dentro de la tarjeta de su crédito.
  const renderPanel = (footer?: ReactNode): ReactNode =>
    typeof panel === "function" ? (
      panel(footer)
    ) : (
      <>
        {panel}
        {footer}
      </>
    );
  const exclusion = exclusionForIssue(issue, decisions);
  const confirmation = confirmationForIssue(issue, decisions);
  const decision = issue.decision;
  const credit = creditToken(issue.location?.credit) || decision?.group_credits?.[0] || "";

  async function run(kind: "exclude" | "undo" | "confirm", fn: () => Promise<string | null>) {
    setBusy(kind);
    setError(null);
    try {
      const err = await fn();
      if (err == null) {
        setMode("idle");
        setConfirmNote("");
      } else {
        setError(err);
      }
    } finally {
      setBusy(null);
    }
  }

  const errorLine = error ? (
    <p className="meta" role="alert" style={{ color: "var(--danger)", margin: "0.4rem 0 0" }}>
      {error}
    </p>
  ) : null;

  if (exclusion) {
    return (
      <div className="decision-box" data-issue-id={issue.issue_id} data-decision="excluded">
        <div className="decision-box-row">
          <span>
            <strong>{issue.title}</strong>
            <span className="meta"> · Excluido · {exclusion.motivo}</span>
          </span>
          {exclusion.can_undo ? (
            <LoadingButton
              variant="secondary"
              className="btn-compact"
              busy={busy === "undo"}
              busyLabel="Deshaciendo…"
              disabled={disabled || busy != null}
              onClick={() =>
                void run("undo", () => handlers.onUndoExclude(exclusion.credit))
              }
            >
              Deshacer
            </LoadingButton>
          ) : null}
        </div>
        {errorLine}
      </div>
    );
  }

  if (confirmation) {
    return (
      <div className="decision-box" data-issue-id={issue.issue_id} data-decision="confirmed">
        <div className="decision-box-row">
          <span>
            <strong>{issue.title}</strong>
            <span className="meta">
              {" "}
              · Continuar con los asientos · {formatCop(confirmation.unapplied_amount)} sin aplicar
            </span>
          </span>
          {confirmation.can_undo ? (
            <LoadingButton
              variant="secondary"
              className="btn-compact"
              busy={busy === "undo"}
              busyLabel="Deshaciendo…"
              disabled={disabled || busy != null}
              onClick={() =>
                void run("undo", () => handlers.onUndoConfirm(confirmation.conciliation_key))
              }
            >
              Deshacer
            </LoadingButton>
          ) : null}
        </div>
        {errorLine}
      </div>
    );
  }

  const excludable = Boolean(decision?.excludable && credit);
  const confirmable = Boolean(decision?.confirmable && decision.conciliation_key);
  if (!excludable && !confirmable) return <>{renderPanel()}</>;

  const groupCredits = decision?.group_credits ?? [];
  const groupWarning = excludable ? groupExclusionWarning(credit, groupCredits) : null;

  const footer = (
    <>
      {mode === "excluding" ? (
        <ExclusionReasonForm
          title={exclusionFormTitle(credit, issue.location?.client_name)}
          submitLabel={excludeSubmitLabel(credit, groupCredits)}
          groupWarning={groupWarning}
          busy={busy === "exclude"}
          disabled={disabled}
          onSubmit={(motivo, nota) =>
            void run("exclude", () => handlers.onExclude(credit, motivo, nota))
          }
          onCancel={() => setMode("idle")}
        />
      ) : (
        <div className="decision-actions">
          {confirmable ? (
            <LoadingButton
              className="btn-compact"
              busy={busy === "confirm"}
              busyLabel="Guardando…"
              disabled={disabled || busy != null}
              onClick={() =>
                void run("confirm", () =>
                  handlers.onConfirm(decision!.conciliation_key!, confirmNote.trim()),
                )
              }
            >
              Continuar con los asientos
            </LoadingButton>
          ) : null}
          {confirmable && mode !== "note" ? (
            <button
              type="button"
              className="decision-link"
              disabled={disabled || busy != null}
              onClick={() => setMode("note")}
            >
              Agregar nota
            </button>
          ) : null}
          {excludable ? (
            <LoadingButton
              variant="secondary"
              className="btn-compact"
              disabled={disabled || busy != null}
              onClick={() => setMode("excluding")}
            >
              {excludeCreditButtonLabel(credit)}
            </LoadingButton>
          ) : null}
        </div>
      )}
      {confirmable && mode === "note" ? (
        <div className="decision-form">
          <input
            type="text"
            aria-label="Nota (opcional)"
            placeholder="Nota (opcional)"
            maxLength={EXCLUSION_NOTE_MAX}
            value={confirmNote}
            onChange={(e) => setConfirmNote(e.target.value)}
          />
        </div>
      ) : null}
      {errorLine}
    </>
  );

  return (
    <div data-issue-decision={issue.issue_id} data-credit={credit}>
      {renderPanel(footer)}
    </div>
  );
}

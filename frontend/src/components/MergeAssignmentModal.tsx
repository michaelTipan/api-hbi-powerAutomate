import { useId, useState } from "react";
import type { UiMergeGroup } from "../types/contract";
import {
  excludeCreditButtonLabel,
  excludeSubmitLabel,
  exclusionFormTitle,
  formatCop,
  groupExclusionWarning,
} from "../domain/amortizationDecisions";
import {
  MSG_IMPOSSIBLE,
  MSG_SHORTFALL,
  MSG_TIE,
  assignableAsientos,
  canConfirmAssignment,
  groupClientLabel,
  groupCreditsLabel,
  hasShortfall,
  initialSelection,
  paymentAssignmentLines,
  paymentLabel,
  shortDate,
  type AssignmentSelection,
  type MergeDecisionHandlers,
} from "../domain/mergeVerification";
import { ExclusionReasonForm } from "./ExclusionReasonForm";
import type { FolderLink } from "./MergeCreditReviewModal";
import { ExternalLinkIcon } from "./LinkIcons";
import { LoadingButton } from "./LoadingButton";
import { Modal } from "./Modal";

/** Ventana «Asignar»: cada asiento a su pago (solo pagos con fecha ≤ fecha del asiento). */
export function MergeAssignmentModal({
  group,
  handlers,
  folderLinks,
  disabled = false,
  onClose,
}: {
  group: UiMergeGroup;
  handlers: MergeDecisionHandlers;
  folderLinks: readonly FolderLink[];
  disabled?: boolean;
  onClose: () => void;
}) {
  const titleId = useId();
  const [selection, setSelection] = useState<AssignmentSelection>(() => initialSelection(group));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [excluding, setExcluding] = useState(false);

  const assignment = group.assignment;
  const usable = assignableAsientos(group);
  const lines = paymentAssignmentLines(group, selection);
  const canConfirm = canConfirmAssignment(group, selection);
  const locked = disabled || busy != null;
  const credit = group.credits[0] ?? "";
  const folders = group.credits
    .map((c) => folderLinks.find((f) => f.credito === c))
    .filter((f): f is FolderLink => Boolean(f?.web_url));

  async function run(kind: string, fn: () => Promise<string | null>, closeOnSuccess = false) {
    setBusy(kind);
    setError(null);
    try {
      const err = await fn();
      if (err == null) {
        setExcluding(false);
        if (closeOnSuccess) onClose();
      } else {
        setError(err);
      }
    } finally {
      setBusy(null);
    }
  }

  function confirm() {
    const items = usable
      .filter((a) => selection[a.path])
      .map((a) => ({ asiento_path: a.path, id_pago: selection[a.path] }));
    void run("assign", () => handlers.onAssign(group.group_key, items), true);
  }

  const title = `Asignar asientos · Crédito ${groupCreditsLabel(group)} · ${groupClientLabel(group)}`;

  return (
    <Modal titleId={titleId} title={title} onClose={onClose} closeDisabled={busy != null}>
      <div className="merge-assignment-modal operational-issues-modal">
        {assignment?.impossible ? (
          <p className="meta" role="status" style={{ marginTop: 0 }}>
            {MSG_IMPOSSIBLE}
          </p>
        ) : assignment?.tie && !assignment.explicit ? (
          <p className="meta" role="status" style={{ marginTop: 0 }}>
            {MSG_TIE}
          </p>
        ) : null}

        <div className="history-table-wrap" style={{ marginTop: "0.25rem" }}>
          <table className="history-table">
            <thead>
              <tr>
                <th>Asiento</th>
                <th>Fecha del asiento</th>
                <th>Valor del asiento</th>
                <th>Pago</th>
                <th>PDF</th>
              </tr>
            </thead>
            <tbody>
              {group.asientos.map((a) => {
                const isUsable = a.state === "usable";
                return (
                  <tr key={a.path} className={isUsable ? undefined : "is-muted"}>
                    <td>{a.numero || a.name}</td>
                    <td>{a.fecha ? shortDate(a.fecha) : "—"}</td>
                    <td>{a.cash == null ? "—" : formatCop(a.cash)}</td>
                    <td>
                      {isUsable ? (
                        <select
                          aria-label={`Pago del asiento ${a.numero || a.name}`}
                          value={selection[a.path] ?? ""}
                          disabled={locked || assignment?.impossible}
                          onChange={(e) =>
                            setSelection((prev) => {
                              const next = { ...prev };
                              if (e.target.value) next[a.path] = e.target.value;
                              else delete next[a.path];
                              return next;
                            })
                          }
                        >
                          <option value="">Seleccione</option>
                          {a.eligible_id_pagos.map((pid) => (
                            <option key={pid} value={pid}>
                              {paymentLabel(group, pid)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span className="meta">{a.state_label}</span>
                      )}
                    </td>
                    <td>
                      {a.web_url ? (
                        <a className="card-link" href={a.web_url} target="_blank" rel="noreferrer">
                          <ExternalLinkIcon />
                          Ver PDF
                        </a>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {!assignment?.impossible ? (
          <ul className="merge-assignment-summary" aria-label="Resumen por pago">
            {lines.map((l) => (
              <li key={l.id_pago} className={`meta is-${l.status}`}>
                {l.text}
              </li>
            ))}
          </ul>
        ) : null}
        {!assignment?.impossible && hasShortfall(group, selection) ? (
          <p className="meta">{MSG_SHORTFALL}</p>
        ) : null}

        {assignment?.impossible ? (
          <div className="decision-actions">
            {folders.map((f) => (
              <a
                key={f.credito}
                className="btn secondary btn-compact"
                href={f.web_url}
                target="_blank"
                rel="noreferrer"
              >
                Abrir carpeta de asientos
              </a>
            ))}
          </div>
        ) : null}

        {group.actions.excluir && !group.exclusion ? (
          excluding ? (
            <ExclusionReasonForm
              title={exclusionFormTitle(credit, group.clientes?.[credit] || group.cliente)}
              submitLabel={excludeSubmitLabel(credit, group.credits)}
              groupWarning={groupExclusionWarning(credit, group.credits)}
              busy={busy === "exclude"}
              disabled={disabled}
              onSubmit={(motivo, nota) =>
                void run("exclude", () => handlers.onExclude(credit, motivo, nota), true)
              }
              onCancel={() => setExcluding(false)}
            />
          ) : (
            <div className="decision-actions">
              <button
                type="button"
                className="decision-link"
                disabled={locked}
                onClick={() => setExcluding(true)}
              >
                {excludeCreditButtonLabel(credit)}
              </button>
            </div>
          )
        ) : null}

        {error ? (
          <p className="meta" role="alert" style={{ color: "var(--danger)", margin: "0.5rem 0 0" }}>
            {error}
          </p>
        ) : null}

        <div className="decision-actions" style={{ justifyContent: "flex-end" }}>
          {assignment?.can_undo ? (
            <LoadingButton
              variant="secondary"
              busy={busy === "undo"}
              busyLabel="Deshaciendo…"
              disabled={locked}
              onClick={() => void run("undo", () => handlers.onUndoAssign(group.group_key), true)}
            >
              Deshacer asignación
            </LoadingButton>
          ) : null}
          <LoadingButton variant="secondary" disabled={busy != null} onClick={onClose}>
            Cerrar
          </LoadingButton>
          {!assignment?.impossible ? (
            <LoadingButton
              busy={busy === "assign"}
              busyLabel="Guardando…"
              disabled={locked || !canConfirm}
              onClick={confirm}
            >
              Confirmar
            </LoadingButton>
          ) : null}
        </div>
      </div>
    </Modal>
  );
}

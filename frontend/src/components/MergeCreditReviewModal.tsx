import { useId, useState } from "react";
import type { UiMergeAsiento, UiMergeFecha, UiMergeGroup } from "../types/contract";
import {
  EXCLUSION_NOTE_MAX,
  excludeCreditButtonLabel,
  excludeSubmitLabel,
  exclusionFormTitle,
  formatCop,
  groupExclusionWarning,
} from "../domain/amortizationDecisions";
import {
  assignedPaymentText,
  assignmentButtonLabel,
  groupClientLabel,
  groupCreditsLabel,
  hasSeveralPaymentDates,
  shortDate,
  unusedReasonFor,
  type MergeDecisionHandlers,
} from "../domain/mergeVerification";
import { ExclusionReasonForm } from "./ExclusionReasonForm";
import { LoadingButton } from "./LoadingButton";
import { Modal } from "./Modal";

export type FolderLink = { credito: string; web_url: string };

const MISSING_DOCS = new Set([
  "FALTA_ASIENTO",
  "ASIENTO_ILEGIBLE",
  "ASIENTO_SIN_VALORES",
  "FALTA_EXTRACTO",
  "FALTA_DOCUMENTO",
]);

function amount(value: number | null | undefined): string {
  return value == null ? "—" : formatCop(value);
}

/** Ventana «Revisar»: consignaciones, asientos y solo las acciones que aplican. */
export function MergeCreditReviewModal({
  group,
  handlers,
  folderLinks,
  disabled = false,
  onClose,
  onOpenAssignment,
}: {
  group: UiMergeGroup;
  handlers: MergeDecisionHandlers;
  folderLinks: readonly FolderLink[];
  disabled?: boolean;
  onClose: () => void;
  onOpenAssignment?: () => void;
}) {
  const titleId = useId();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [excluding, setExcluding] = useState(false);
  const [confirmNote, setConfirmNote] = useState("");

  async function run(kind: string, fn: () => Promise<string | null>) {
    setBusy(kind);
    setError(null);
    try {
      const err = await fn();
      if (err == null) {
        setExcluding(false);
        setConfirmNote("");
      } else {
        setError(err);
      }
    } finally {
      setBusy(null);
    }
  }

  const locked = disabled || busy != null;
  const credit = group.credits[0] ?? "";
  const folders = group.credits
    .map((c) => folderLinks.find((f) => f.credito === c))
    .filter((f): f is FolderLink => Boolean(f?.web_url));
  const needsDocs = group.motivos.some((m) => MISSING_DOCS.has(m.code));
  const showPago = hasSeveralPaymentDates(group);
  const title = `Crédito ${groupCreditsLabel(group)} · ${groupClientLabel(group)}`;

  function asientoAction(a: UiMergeAsiento) {
    if (a.can_undo_unused) {
      return (
        <button
          type="button"
          className="decision-link"
          disabled={locked}
          onClick={() => void run(`undo-${a.path}`, () => handlers.onUndoUnused(a.path))}
        >
          Deshacer
        </button>
      );
    }
    if (a.can_mark_unused && group.actions.no_corresponde && group.status !== "excluded") {
      return (
        <button
          type="button"
          className="decision-link"
          disabled={locked}
          onClick={() =>
            void run(`unused-${a.path}`, () => handlers.onMarkUnused(a.path, unusedReasonFor(a)))
          }
        >
          No corresponde a este pago
        </button>
      );
    }
    return null;
  }

  function fechaBlock(f: UiMergeFecha) {
    if (f.status === "OK") return null;
    const head = `Pago ${shortDate(f.fecha)}: banco ${amount(f.monto_banco)} · según asientos ${amount(f.monto_asientos)}`;
    if (f.status === "CONFIRMED") {
      return (
        <div key={f.conciliation_key} className="decision-box" data-decision="confirmed">
          <div className="decision-box-row">
            <span>
              {head}
              <span className="meta"> · Continuar con los asientos · {amount(f.diferencia)} sin aplicar</span>
            </span>
            {f.confirmation?.can_undo ? (
              <LoadingButton
                variant="secondary"
                className="btn-compact"
                busy={busy === `undo-${f.conciliation_key}`}
                busyLabel="Deshaciendo…"
                disabled={locked}
                onClick={() =>
                  void run(`undo-${f.conciliation_key}`, () => handlers.onUndoConfirm(f.conciliation_key))
                }
              >
                Deshacer
              </LoadingButton>
            ) : null}
          </div>
        </div>
      );
    }
    if (f.status === "BANK_GREATER") {
      return (
        <div key={f.conciliation_key} className="merge-review-block">
          <p className="meta" style={{ margin: 0 }}>
            {head}. El banco recibió {amount(f.diferencia)} más de lo registrado.
          </p>
          {group.actions.continuar && group.status !== "excluded" ? (
            <div className="decision-form">
              <input
                type="text"
                aria-label="Nota (opcional)"
                placeholder="Nota (opcional)"
                maxLength={EXCLUSION_NOTE_MAX}
                value={confirmNote}
                onChange={(e) => setConfirmNote(e.target.value)}
              />
              <div className="decision-actions" style={{ marginTop: 0 }}>
                <LoadingButton
                  className="btn-compact"
                  busy={busy === `confirm-${f.conciliation_key}`}
                  busyLabel="Guardando…"
                  disabled={locked}
                  onClick={() =>
                    void run(`confirm-${f.conciliation_key}`, () =>
                      handlers.onConfirm(f.conciliation_key, confirmNote.trim()),
                    )
                  }
                >
                  Continuar con los asientos
                </LoadingButton>
              </div>
            </div>
          ) : null}
        </div>
      );
    }
    return (
      <p key={f.conciliation_key} className="meta">
        {head}. Los asientos superan lo recibido por el banco: revise si hay un asiento que no
        corresponde a este pago.
      </p>
    );
  }

  return (
    <Modal titleId={titleId} title={title} onClose={onClose} closeDisabled={busy != null}>
      <div className="merge-review-modal operational-issues-modal">
        {group.motivos.length > 0 ? (
          <p className="meta" style={{ marginTop: 0 }}>
            {group.motivos.map((m) => m.label).join(" · ")}
          </p>
        ) : null}

        <h3 className="merge-review-heading">Consignaciones</h3>
        <div className="history-table-wrap" style={{ marginTop: "0.25rem" }}>
          <table className="history-table">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Monto</th>
                <th>Tipo de aplicación</th>
              </tr>
            </thead>
            <tbody>
              {group.consignaciones.map((c) => (
                <tr key={c.id_pago}>
                  <td>{shortDate(c.fecha)}</td>
                  <td className="nowrap">{amount(c.monto)}</td>
                  <td>{c.tipo || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <h3 className="merge-review-heading">Asientos</h3>
        {group.asientos.length === 0 ? (
          <p className="meta">No hay asientos en la carpeta del crédito.</p>
        ) : (
          <div className="history-table-wrap" style={{ marginTop: "0.25rem" }}>
            <table className="history-table">
              <thead>
                <tr>
                  <th>Número</th>
                  <th>Fecha</th>
                  <th>Valor del asiento</th>
                  {showPago ? <th>Pago</th> : null}
                  {group.has_retenciones ? <th>Retenciones</th> : null}
                  {group.has_saldos_menores ? <th>Saldos menores</th> : null}
                  <th>PDF</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {group.asientos.map((a) => (
                  <tr key={a.path} className={a.state === "usable" ? undefined : "is-muted"}>
                    <td>
                      {a.numero || a.name}
                      {a.state_label ? <span className="meta d-block">{a.state_label}</span> : null}
                    </td>
                    <td>{a.fecha ? shortDate(a.fecha) : "—"}</td>
                    <td className="nowrap">{amount(a.cash)}</td>
                    {showPago ? (
                      <td className="nowrap">{assignedPaymentText(group, a.assigned_id_pago)}</td>
                    ) : null}
                    {group.has_retenciones ? <td className="nowrap">{amount(a.retenciones)}</td> : null}
                    {group.has_saldos_menores ? <td className="nowrap">{amount(a.saldos_menores)}</td> : null}
                    <td>
                      {a.web_url ? (
                        <a href={a.web_url} target="_blank" rel="noreferrer">
                          Ver PDF
                        </a>
                      ) : null}
                    </td>
                    <td>{asientoAction(a)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {group.fechas.map(fechaBlock)}

        {group.actions.asignar && onOpenAssignment && group.status !== "excluded" ? (
          <div className="decision-actions">
            <LoadingButton className="btn-compact" disabled={locked} onClick={onOpenAssignment}>
              {assignmentButtonLabel(group)}
            </LoadingButton>
          </div>
        ) : null}

        {needsDocs && group.status !== "excluded" ? (
          <div className="decision-actions">
            {folders.map((f) => (
              <a
                key={f.credito}
                className="btn secondary btn-compact"
                href={f.web_url}
                target="_blank"
                rel="noreferrer"
              >
                {folders.length > 1 ? `Abrir carpeta de asientos (${f.credito})` : "Abrir carpeta de asientos"}
              </a>
            ))}
            <LoadingButton variant="secondary" className="btn-compact" disabled={locked} onClick={handlers.onVerify}>
              Verificar de nuevo
            </LoadingButton>
          </div>
        ) : null}

        {group.exclusion ? (
          <div className="decision-box" data-decision="excluded">
            <div className="decision-box-row">
              <span>
                <strong>Excluido</strong>
                <span className="meta"> · {group.exclusion.motivo}</span>
              </span>
              {group.exclusion.can_undo ? (
                <LoadingButton
                  variant="secondary"
                  className="btn-compact"
                  busy={busy === "undo-exclude"}
                  busyLabel="Deshaciendo…"
                  disabled={locked}
                  onClick={() => void run("undo-exclude", () => handlers.onUndoExclude(credit))}
                >
                  Deshacer
                </LoadingButton>
              ) : null}
            </div>
          </div>
        ) : group.actions.excluir ? (
          excluding ? (
            <ExclusionReasonForm
              title={exclusionFormTitle(credit, group.clientes?.[credit] || group.cliente)}
              submitLabel={excludeSubmitLabel(credit, group.credits)}
              groupWarning={groupExclusionWarning(credit, group.credits)}
              busy={busy === "exclude"}
              disabled={disabled}
              onSubmit={(motivo, nota) => void run("exclude", () => handlers.onExclude(credit, motivo, nota))}
              onCancel={() => setExcluding(false)}
            />
          ) : (
            <div className="decision-actions">
              <LoadingButton
                variant="secondary"
                className="btn-compact"
                disabled={locked}
                onClick={() => setExcluding(true)}
              >
                {excludeCreditButtonLabel(credit)}
              </LoadingButton>
            </div>
          )
        ) : null}

        {error ? (
          <p className="meta" role="alert" style={{ color: "var(--danger)", margin: "0.5rem 0 0" }}>
            {error}
          </p>
        ) : null}

        <div className="decision-actions" style={{ justifyContent: "flex-end" }}>
          <LoadingButton variant="secondary" disabled={busy != null} onClick={onClose}>
            Cerrar
          </LoadingButton>
        </div>
      </div>
    </Modal>
  );
}

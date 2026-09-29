import { useId, useState } from "react";
import type { UiMergeAsiento, UiMergeFecha, UiMergeGroup } from "../types/contract";
import { EXCLUSION_NOTE_MAX, formatCop, groupExclusionWarning } from "../domain/amortizationDecisions";
import {
  groupClientLabel,
  groupCreditsLabel,
  shortDate,
  unusedReasonFor,
  type MergeDecisionHandlers,
} from "../domain/mergeVerification";
import { ExclusionReasonForm } from "./ExclusionReasonForm";
import { LoadingButton } from "./LoadingButton";
import { Modal } from "./Modal";

export type FolderLink = { credito: string; web_url: string };

const MISSING_DOCS = new Set(["FALTA_ASIENTO", "ASIENTO_ILEGIBLE", "FALTA_EXTRACTO", "FALTA_DOCUMENTO"]);

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
  const [tipoChoice, setTipoChoice] = useState(group.tipo?.sugerido ?? group.tipo?.opciones[0] ?? "");
  const [tipoNote, setTipoNote] = useState("");

  async function run(kind: string, fn: () => Promise<string | null>) {
    setBusy(kind);
    setError(null);
    try {
      const err = await fn();
      if (err == null) {
        setExcluding(false);
        setConfirmNote("");
        setTipoNote("");
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

  const tipo = group.tipo;

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
                <th>Concepto</th>
              </tr>
            </thead>
            <tbody>
              {group.consignaciones.map((c) => (
                <tr key={c.id_pago}>
                  <td>{shortDate(c.fecha)}</td>
                  <td>{amount(c.monto)}</td>
                  <td>{c.concepto || c.tipo}</td>
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
                  <th>Recibido en banco</th>
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
                    <td>{amount(a.cash)}</td>
                    {group.has_retenciones ? <td>{amount(a.retenciones)}</td> : null}
                    {group.has_saldos_menores ? <td>{amount(a.saldos_menores)}</td> : null}
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
              {group.assignment?.explicit ? "Modificar asignación" : "Asignar asientos a sus pagos"}
            </LoadingButton>
          </div>
        ) : null}

        {tipo?.needed && group.status !== "excluded" ? (
          <div className="merge-review-block">
            <p className="meta" style={{ margin: 0 }}>
              Tipo declarado: {tipo.declarado}. Según los asientos: {tipo.sugerido ?? "—"}.
              El cambio solo afecta el nombre del consolidado y el extracto; los valores siguen
              siendo los de los asientos.
            </p>
            <div className="decision-form">
              <label>
                <span>Tipo</span>
                <select
                  aria-label="Tipo según los asientos"
                  value={tipoChoice}
                  onChange={(e) => setTipoChoice(e.target.value)}
                >
                  {tipo.opciones.map((o) => (
                    <option key={o} value={o}>
                      {o}
                    </option>
                  ))}
                </select>
              </label>
              <textarea
                aria-label="Nota (obligatoria)"
                placeholder="Nota (obligatoria)"
                rows={2}
                maxLength={EXCLUSION_NOTE_MAX}
                value={tipoNote}
                onChange={(e) => setTipoNote(e.target.value)}
              />
              <div className="decision-actions" style={{ marginTop: 0 }}>
                <LoadingButton
                  className="btn-compact"
                  busy={busy === "tipo"}
                  busyLabel="Guardando…"
                  disabled={locked || !tipoChoice || tipoNote.trim().length === 0}
                  onClick={() =>
                    void run("tipo", () => handlers.onUseTipo(tipo.id_pago, tipoChoice, tipoNote.trim()))
                  }
                >
                  Usar el tipo según los asientos
                </LoadingButton>
              </div>
            </div>
          </div>
        ) : null}
        {tipo?.correction ? (
          <div className="decision-box" data-decision="tipo">
            <div className="decision-box-row">
              <span>
                Tipo usado: {tipo.actual}
                <span className="meta"> · declarado {tipo.declarado}</span>
              </span>
              {tipo.correction.can_undo ? (
                <LoadingButton
                  variant="secondary"
                  className="btn-compact"
                  busy={busy === "undo-tipo"}
                  busyLabel="Deshaciendo…"
                  disabled={locked}
                  onClick={() => void run("undo-tipo", () => handlers.onUndoTipo(tipo.id_pago))}
                >
                  Deshacer
                </LoadingButton>
              ) : null}
            </div>
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
                Excluir crédito
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

import { useState } from "react";
import type { UiMergeGroup, UiMergeVerification } from "../types/contract";
import { formatCop } from "../domain/amortizationDecisions";
import {
  groupClientLabel,
  groupCreditsLabel,
  groupStatusChips,
  orderedGroups,
  verificationSummary,
  type MergeDecisionHandlers,
} from "../domain/mergeVerification";
import { LoadingButton } from "./LoadingButton";
import { MergeAssignmentModal } from "./MergeAssignmentModal";
import { MergeCreditReviewModal, type FolderLink } from "./MergeCreditReviewModal";

type OpenWindow = { kind: "review" | "assign"; groupKey: string } | null;

function amountCell(value: number | null | undefined): string {
  return value == null ? "—" : formatCop(value);
}

/** Fase 3, tarjeta principal: «N de M créditos listos» y volver a verificar. */
export function MergeVerificationSummary({
  verification,
  handlers,
  verifying = false,
}: {
  verification: UiMergeVerification;
  handlers: Pick<MergeDecisionHandlers, "onVerify">;
  verifying?: boolean;
}) {
  return (
    <div className="merge-verification-panel">
      <p className="merge-verification-summary" role="status">
        {verificationSummary(verification)}
      </p>
      {verification.all_excluded ? (
        <p className="meta">
          Todos los créditos están excluidos. Deshaga una exclusión para consolidar o cancele el proceso.
        </p>
      ) : null}
      <div className="merge-verify-actions decision-actions">
        <LoadingButton
          variant="secondary"
          className="btn-compact"
          busy={verifying}
          busyLabel="Verificando…"
          disabled={verifying}
          onClick={handlers.onVerify}
        >
          Verificar de nuevo
        </LoadingButton>
      </div>
    </div>
  );
}

/** Fase 3, tarjeta propia: todos los créditos del lote, primero los que requieren atención. */
export function MergeVerificationTable({
  verification,
  handlers,
  folderLinks,
  disabled = false,
}: {
  verification: UiMergeVerification;
  handlers: MergeDecisionHandlers;
  folderLinks: readonly FolderLink[];
  disabled?: boolean;
}) {
  const [open, setOpen] = useState<OpenWindow>(null);
  const rows = orderedGroups(verification);
  const openGroup = open
    ? verification.groups.find((g) => g.group_key === open.groupKey) ?? null
    : null;

  function actionFor(group: UiMergeGroup) {
    const asignar = group.status === "attention" && group.primary_action === "asignar";
    return (
      <span className="merge-row-actions">
        <LoadingButton
          variant={group.status === "attention" ? "primary" : "secondary"}
          className="btn-compact"
          disabled={disabled}
          onClick={() => setOpen({ kind: asignar ? "assign" : "review", groupKey: group.group_key })}
        >
          {asignar ? "Asignar" : "Revisar"}
        </LoadingButton>
        {asignar ? (
          <button
            type="button"
            className="decision-link"
            disabled={disabled}
            onClick={() => setOpen({ kind: "review", groupKey: group.group_key })}
          >
            Revisar
          </button>
        ) : null}
      </span>
    );
  }

  function foldersFor(group: UiMergeGroup) {
    const links = group.credits
      .map((c) => folderLinks.find((f) => f.credito === c))
      .filter((f): f is FolderLink => Boolean(f?.web_url));
    if (links.length === 0) return "—";
    return (
      <span className="merge-row-folders">
        {links.map((f) => (
          <a key={f.credito} href={f.web_url} target="_blank" rel="noreferrer">
            {links.length > 1 ? `Abrir carpeta (${f.credito})` : "Abrir carpeta"}
          </a>
        ))}
      </span>
    );
  }

  return (
    <>
      <div className="history-table-wrap merge-verification-table-wrap" style={{ marginTop: 0 }}>
        <table className="history-table merge-verification-table">
          <thead>
            <tr>
              <th>Cliente</th>
              <th>Crédito</th>
              <th>Estado</th>
              <th>Consignado</th>
              <th>Según asientos</th>
              <th>Diferencia</th>
              <th>Asientos</th>
              <th className="merge-action-col">
                <span className="sr-only">Acción</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((g) => (
              <tr key={g.group_key} className={g.status === "excluded" ? "is-muted" : undefined}>
                <td>{groupClientLabel(g)}</td>
                <td className="nowrap">{groupCreditsLabel(g)}</td>
                <td>
                  <span className="merge-status-chips">
                    {groupStatusChips(g).map((chip) => (
                      <span key={chip.label} className={`merge-status-chip ${chip.tone}`}>
                        {chip.label}
                      </span>
                    ))}
                  </span>
                  {g.status === "excluded" && g.exclusion?.motivo ? (
                    <span className="meta d-block">{g.exclusion.motivo}</span>
                  ) : null}
                </td>
                <td className="nowrap">{amountCell(g.consignado)}</td>
                <td className="nowrap">{amountCell(g.segun_asientos)}</td>
                <td className="nowrap">{amountCell(g.pendiente)}</td>
                <td className="nowrap">{foldersFor(g)}</td>
                <td className="merge-action-col">{actionFor(g)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && openGroup && open.kind === "review" ? (
        <MergeCreditReviewModal
          group={openGroup}
          handlers={handlers}
          folderLinks={folderLinks}
          disabled={disabled}
          onClose={() => setOpen(null)}
          onOpenAssignment={() => setOpen({ kind: "assign", groupKey: openGroup.group_key })}
        />
      ) : null}
      {open && openGroup && open.kind === "assign" ? (
        <MergeAssignmentModal
          group={openGroup}
          handlers={handlers}
          folderLinks={folderLinks}
          disabled={disabled}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </>
  );
}

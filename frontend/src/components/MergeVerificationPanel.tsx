import { useState } from "react";
import type { UiMergeGroup, UiMergeVerification } from "../types/contract";
import { formatCop } from "../domain/amortizationDecisions";
import {
  attentionGroups,
  excludedGroups,
  groupClientLabel,
  groupCreditsLabel,
  motivosLine,
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

function statusText(group: UiMergeGroup): string {
  if (group.status === "ready") return "Listo";
  if (group.status === "excluded") return `Excluido · ${group.exclusion?.motivo ?? ""}`.trim();
  return motivosLine(group);
}

/** Fase 3: resumen «N de M créditos listos» y lo que requiere atención. */
export function MergeVerificationPanel({
  verification,
  handlers,
  folderLinks,
  disabled = false,
  verifying = false,
}: {
  verification: UiMergeVerification;
  handlers: MergeDecisionHandlers;
  folderLinks: readonly FolderLink[];
  disabled?: boolean;
  verifying?: boolean;
}) {
  const [showAll, setShowAll] = useState(false);
  const [open, setOpen] = useState<OpenWindow>(null);
  const attention = attentionGroups(verification);
  const excluded = excludedGroups(verification);
  const rows = showAll ? verification.groups : attention;
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

      {rows.length > 0 ? (
        <>
          <h3 className="merge-review-heading">{showAll ? "Todos los créditos" : "Requieren atención"}</h3>
          <div className="history-table-wrap" style={{ marginTop: "0.25rem" }}>
            <table className="history-table merge-verification-table">
              <thead>
                <tr>
                  <th>Cliente</th>
                  <th>Crédito</th>
                  <th>Consignado</th>
                  <th>Según asientos</th>
                  <th>Pendiente</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((g) => (
                  <tr key={g.group_key} className={g.status === "excluded" ? "is-muted" : undefined}>
                    <td>
                      {groupClientLabel(g)}
                      <span className="meta d-block">{statusText(g)}</span>
                    </td>
                    <td>{groupCreditsLabel(g)}</td>
                    <td>{amountCell(g.consignado)}</td>
                    <td>{amountCell(g.segun_asientos)}</td>
                    <td>{amountCell(g.pendiente)}</td>
                    <td>{actionFor(g)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      {!showAll && excluded.length > 0 ? (
        <div className="amortization-exclusions" style={{ marginTop: "0.5rem" }}>
          {excluded.map((g) => (
            <p key={g.group_key} className="meta" style={{ margin: "0.15rem 0" }}>
              Excluido: crédito {groupCreditsLabel(g)} · {groupClientLabel(g)}
              {g.exclusion?.motivo ? ` · ${g.exclusion.motivo}` : ""}{" "}
              <button
                type="button"
                className="decision-link"
                disabled={disabled}
                onClick={() => setOpen({ kind: "review", groupKey: g.group_key })}
              >
                Revisar
              </button>
            </p>
          ))}
        </div>
      ) : null}

      <div className="merge-verify-actions decision-actions">
        {verification.groups.length > attention.length ? (
          <button type="button" className="decision-link" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Ver solo los que requieren atención" : "Ver todos los créditos"}
          </button>
        ) : null}
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
    </div>
  );
}

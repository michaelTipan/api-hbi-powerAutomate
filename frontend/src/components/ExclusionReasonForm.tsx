import { useId, useState } from "react";
import type { ExclusionReasonCode } from "../types/contract";
import { EXCLUSION_NOTE_MAX, EXCLUSION_REASONS } from "../domain/amortizationDecisions";
import { LoadingButton } from "./LoadingButton";

/** Motivo de exclusión (mismos motivos en Consolidar y Amortizar). */
export function ExclusionReasonForm({
  groupWarning,
  busy,
  disabled = false,
  onSubmit,
  onCancel,
}: {
  groupWarning?: string | null;
  busy: boolean;
  disabled?: boolean;
  onSubmit: (motivo: ExclusionReasonCode, nota: string) => void;
  onCancel: () => void;
}) {
  const formId = useId();
  const [motivo, setMotivo] = useState<ExclusionReasonCode | null>(null);
  const [nota, setNota] = useState("");
  const needsText = motivo === "OTRO";
  const canSubmit = motivo != null && (!needsText || nota.trim().length > 0) && !busy && !disabled;

  return (
    <div className="decision-form" role="group" aria-labelledby={`${formId}-title`}>
      <strong id={`${formId}-title`}>Motivo de la exclusión</strong>
      {EXCLUSION_REASONS.map((r) => (
        <label key={r.code}>
          <input
            type="radio"
            name={`${formId}-motivo`}
            value={r.code}
            checked={motivo === r.code}
            onChange={() => setMotivo(r.code)}
          />
          <span>{r.label}</span>
        </label>
      ))}
      {needsText ? (
        <textarea
          aria-label="Especifique el motivo"
          rows={2}
          maxLength={EXCLUSION_NOTE_MAX}
          value={nota}
          onChange={(e) => setNota(e.target.value)}
        />
      ) : null}
      {groupWarning ? <p className="meta">{groupWarning}</p> : null}
      <div className="decision-actions">
        <LoadingButton
          variant="danger"
          className="btn-compact"
          busy={busy}
          busyLabel="Excluyendo…"
          disabled={!canSubmit}
          onClick={() => motivo && onSubmit(motivo, needsText ? nota.trim() : "")}
        >
          Excluir
        </LoadingButton>
        <LoadingButton variant="secondary" className="btn-compact" disabled={busy} onClick={onCancel}>
          Cancelar
        </LoadingButton>
      </div>
    </div>
  );
}

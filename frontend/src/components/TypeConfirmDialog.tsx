import { useId, useState, type ReactNode } from "react";
import { Modal } from "./Modal";
import { LoadingButton } from "./LoadingButton";

/** Confirmación fuerte: el operador debe escribir exactamente la palabra dada. */
export function TypeConfirmDialog({
  title,
  children,
  confirmWord = "CANCELAR",
  confirmLabel,
  busyLabel,
  busy = false,
  reasonRequired = false,
  reasonLabel = "Motivo",
  reasonPlaceholder = "Escriba un motivo corto",
  onConfirm,
  onCancel,
}: {
  title: string;
  children: ReactNode;
  confirmWord?: string;
  confirmLabel: string;
  busyLabel?: string;
  busy?: boolean;
  reasonRequired?: boolean;
  reasonLabel?: string;
  reasonPlaceholder?: string;
  onConfirm: (payload: { reason: string }) => void;
  onCancel: () => void;
}) {
  const titleId = useId();
  const descriptionId = useId();
  const confirmInputId = useId();
  const reasonInputId = useId();
  const [typed, setTyped] = useState("");
  const [reason, setReason] = useState("");

  const wordOk = typed.trim() === confirmWord;
  const reasonOk = !reasonRequired || reason.trim().length >= 3;
  const canConfirm = wordOk && reasonOk && !busy;

  return (
    <Modal
      titleId={titleId}
      title={title}
      descriptionId={descriptionId}
      onClose={onCancel}
      closeDisabled={busy}
    >
      <div id={descriptionId}>{children}</div>
      {reasonRequired ? (
        <label className="type-confirm-field" htmlFor={reasonInputId}>
          <span className="type-confirm-label">{reasonLabel}</span>
          <textarea
            id={reasonInputId}
            className="type-confirm-reason"
            rows={2}
            maxLength={280}
            value={reason}
            disabled={busy}
            placeholder={reasonPlaceholder}
            onChange={(e) => setReason(e.target.value)}
          />
        </label>
      ) : null}
      <label className="type-confirm-field" htmlFor={confirmInputId}>
        <span className="type-confirm-label">
          Para confirmar, escriba <strong>{confirmWord}</strong>
        </span>
        <input
          id={confirmInputId}
          className="type-confirm-input"
          type="text"
          autoComplete="off"
          spellCheck={false}
          value={typed}
          disabled={busy}
          placeholder={confirmWord}
          onChange={(e) => setTyped(e.target.value)}
        />
      </label>
      <div className="actions">
        <LoadingButton
          busy={busy}
          busyLabel={busyLabel}
          disabled={!canConfirm}
          onClick={() => onConfirm({ reason: reason.trim() })}
        >
          {confirmLabel}
        </LoadingButton>
        <button type="button" className="btn secondary" disabled={busy} onClick={onCancel}>
          Volver
        </button>
      </div>
    </Modal>
  );
}
